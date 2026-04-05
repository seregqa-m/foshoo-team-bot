import logging
import os
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db

router = APIRouter(prefix="/api/finance", tags=["finance"])
logger = logging.getLogger(__name__)

EXPENSE_TYPES = ["Личные траты", "Трата со счета ФоШу", "Пожертвование"]
PROJECTS = ["Театр", "Любовь Громова", "Урод", "Слепые"]


def _get_client():
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(status_code=503, detail="Google Sheets не настроен")
    return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)


def _resolve_name(username: str) -> str:
    """Получить полное имя актёра по username. Если не найден — вернуть username."""
    try:
        client = _get_client()
        mapping = client.get_actor_mapping()
        return mapping.get(username.lower().lstrip("@"), username)
    except Exception:
        return username


@router.get("/balance")
async def get_balance():
    try:
        client = _get_client()
        return {"balance": client.get_balance()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_balance failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meta")
async def get_meta():
    """Вернуть списки проектов, типов трат и актёров для форм."""
    from config import GOOGLE_SHEETS_ID
    actors = []
    try:
        client = _get_client()
        mapping = client.get_actor_mapping()
        actors = sorted(mapping.values())
    except Exception:
        pass
    sheets_url = None
    if GOOGLE_SHEETS_ID:
        try:
            gid = _get_client()._get_sheet_id("Финансы")
            sheets_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}/edit#gid={gid}"
        except Exception:
            sheets_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}"
    return {"projects": PROJECTS, "expense_types": EXPENSE_TYPES, "actors": actors, "sheets_url": sheets_url}


@router.get("/whoami")
async def whoami(username: str = ""):
    """Вернуть полное имя актёра по Telegram username."""
    return {"name": _resolve_name(username) if username else ""}


class ExpenseRequest(BaseModel):
    project: str
    amount: str
    what: str
    expense_type: str
    comment: str = ""
    username: str = ""  # Telegram username для резолва имени
    who: str = ""       # если передан явно — используется как есть
    date: str = ""      # DD.MM.YYYY; если пусто — сегодня


class IncomeRequest(BaseModel):
    project: str
    amount: str
    what: str
    comment: str = ""
    date: str = ""      # DD.MM.YYYY; если пусто — сегодня


@router.post("/expense")
async def add_expense(req: ExpenseRequest, db: Session = Depends(get_db)):
    if req.project not in PROJECTS:
        raise HTTPException(status_code=400, detail="Неверный проект")
    if req.expense_type not in EXPENSE_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип траты")

    who = req.who.strip() if req.who.strip() else (_resolve_name(req.username) if req.username else "—")
    today = req.date.strip() if req.date.strip() else date.today().strftime("%d.%m.%Y")

    try:
        client = _get_client()
        client.add_expense(req.project, today, who, req.amount, req.what, req.expense_type, req.comment)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_expense sheets failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    from modules.finance.models import ExpenseLog
    db.add(ExpenseLog(project=req.project, date=today, who=who, amount=req.amount,
                      what=req.what, expense_type=req.expense_type, comment=req.comment))
    db.commit()
    return {"status": "added"}


@router.get("/chart")
async def get_chart(period: str = "month", from_date: str = None, db: Session = Depends(get_db)):
    """
    period=month: все доходы/расходы по месяцам с разбивкой по типу расхода.
    period=day:   P&L — только ФоШу-траты + Возвраты, полный период.
    """
    from modules.finance.models import ExpenseLog, IncomeLog, ReturnsLog
    from collections import defaultdict

    def date_tuple(s: str) -> tuple:
        try:
            d, m, y = s.strip().split(".")
            return (int(y), int(m), int(d))
        except Exception:
            return (0, 0, 0)

    def parse_amount(raw) -> float:
        s = str(raw).replace("р.", "").replace("₽", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        return float(s)

    if period == "day":
        # P&L: доходы − ФоШу-траты − Возвраты, полный период
        income_agg: dict[str, float] = defaultdict(float)
        expense_agg: dict[str, float] = defaultdict(float)

        for row in db.query(IncomeLog).all():
            if row.date:
                try:
                    income_agg[row.date] += parse_amount(row.amount)
                except (ValueError, TypeError):
                    pass

        for row in db.query(ExpenseLog).filter(ExpenseLog.expense_type == "Трата со счета ФоШу").all():
            if row.date:
                try:
                    expense_agg[row.date] += parse_amount(row.amount)
                except (ValueError, TypeError):
                    pass

        for row in db.query(ReturnsLog).all():
            if row.date:
                try:
                    expense_agg[row.date] += parse_amount(row.amount)
                except (ValueError, TypeError):
                    pass

        # Полный период от первой транзакции до сегодня
        all_dates = set(income_agg) | set(expense_agg)
        if not all_dates:
            return {"data": []}
        def to_date(s):
            try:
                d, m, y = s.strip().split(".")
                return date(int(y), int(m), int(d))
            except Exception:
                return None
        valid = [to_date(d) for d in all_dates if to_date(d)]
        start = min(valid)
        today_date = date.today()
        all_keys, cur = [], start
        while cur <= today_date:
            all_keys.append(cur.strftime("%d.%m.%Y"))
            cur += timedelta(days=1)

        data = [
            {"period": k, "income": round(income_agg[k]), "expense": round(expense_agg[k])}
            for k in all_keys
        ]
        return {"data": data}

    # period == "month"
    def month_key(date_str: str) -> str | None:
        try:
            parts = date_str.strip().split(".")
            return f"{parts[1]}.{parts[2]}" if len(parts) == 3 else None
        except Exception:
            return None

    def month_sort(label: str) -> tuple:
        try:
            m, y = label.split(".")
            return (int(y), int(m))
        except Exception:
            return (0, 0)

    from_tuple = date_tuple(from_date) if from_date else None

    income_agg: dict[str, float] = defaultdict(float)
    exp_foshu: dict[str, float] = defaultdict(float)
    exp_personal: dict[str, float] = defaultdict(float)
    exp_donation: dict[str, float] = defaultdict(float)

    for row in db.query(IncomeLog).all():
        if from_tuple and date_tuple(row.date) < from_tuple:
            continue
        k = month_key(row.date)
        if k:
            try:
                income_agg[k] += parse_amount(row.amount)
            except (ValueError, TypeError):
                pass

    for row in db.query(ExpenseLog).all():
        if from_tuple and date_tuple(row.date) < from_tuple:
            continue
        k = month_key(row.date)
        if not k:
            continue
        try:
            amt = parse_amount(row.amount)
        except (ValueError, TypeError):
            continue
        if row.expense_type == "Трата со счета ФоШу":
            exp_foshu[k] += amt
        elif row.expense_type == "Личные траты":
            exp_personal[k] += amt
        elif row.expense_type in ("Пожертвование", "Пожертвования"):
            exp_donation[k] += amt
        else:
            exp_foshu[k] += amt  # неизвестный тип → считаем основным

    all_keys = sorted(
        set(income_agg) | set(exp_foshu) | set(exp_personal) | set(exp_donation),
        key=month_sort
    )
    data = [
        {
            "period": k,
            "income": round(income_agg[k]),
            "expense_foshu": round(exp_foshu[k]),
            "expense_personal": round(exp_personal[k]),
            "expense_donation": round(exp_donation[k]),
            "expense": round(exp_foshu[k] + exp_personal[k] + exp_donation[k]),
        }
        for k in all_keys
    ]
    return {"data": data}


@router.post("/sync-returns")
async def sync_returns(db: Session = Depends(get_db)):
    """Синхронизировать таблицу Возвраты из Google Sheets."""
    from modules.finance.models import ReturnsLog
    try:
        client = _get_client()
        rows = client.get_returns()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.query(ReturnsLog).delete()
    for r in rows:
        db.add(ReturnsLog(project=r["project"], who=r["who"], amount=r["amount"], date=r["date"]))
    db.commit()
    return {"status": "synced", "count": len(rows)}


@router.get("/transactions")
async def get_transactions(limit: int = 10, db: Session = Depends(get_db)):
    """Последние N операций (доходы + расходы) из БД, отсортированные по дате добавления."""
    from modules.finance.models import ExpenseLog, IncomeLog
    expenses = db.query(ExpenseLog).all()
    incomes = db.query(IncomeLog).all()
    items = []
    for e in expenses:
        items.append({"id": e.id, "type": "expense", "date": e.date, "amount": e.amount,
                      "what": e.what, "project": e.project, "who": e.who,
                      "expense_type": e.expense_type, "comment": e.comment or "",
                      "created_at": e.created_at.isoformat() if e.created_at else ""})
    for i in incomes:
        items.append({"id": i.id, "type": "income", "date": i.date, "amount": i.amount,
                      "what": i.what, "project": i.project, "who": "",
                      "expense_type": "", "comment": i.comment or "",
                      "created_at": i.created_at.isoformat() if i.created_at else ""})
    def date_sort_key(x):
        try:
            d, m, y = x["date"].strip().split(".")
            return (int(y), int(m), int(d))
        except Exception:
            return (0, 0, 0)

    items.sort(key=date_sort_key, reverse=True)
    return {"transactions": items[:limit]}


@router.delete("/transactions/{tx_type}/{tx_id}")
async def delete_transaction(tx_type: str, tx_id: int, db: Session = Depends(get_db)):
    """Удалить операцию из БД и Google Sheets."""
    from modules.finance.models import ExpenseLog, IncomeLog
    if tx_type == "expense":
        row = db.query(ExpenseLog).filter(ExpenseLog.id == tx_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            _get_client().delete_expense_row(row.date, row.what)
        except Exception as e:
            logger.warning(f"Sheets delete expense failed: {e}")
        db.delete(row)
    elif tx_type == "income":
        row = db.query(IncomeLog).filter(IncomeLog.id == tx_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            _get_client().delete_income_row(row.date, row.what)
        except Exception as e:
            logger.warning(f"Sheets delete income failed: {e}")
        db.delete(row)
    else:
        raise HTTPException(status_code=400, detail="Invalid type")
    db.commit()
    return {"status": "deleted"}


@router.post("/income")
async def add_income(req: IncomeRequest, db: Session = Depends(get_db)):
    if req.project not in PROJECTS:
        raise HTTPException(status_code=400, detail="Неверный проект")

    today = req.date.strip() if req.date.strip() else date.today().strftime("%d.%m.%Y")

    try:
        client = _get_client()
        client.add_income(req.project, req.amount, req.what, today, req.comment)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_income sheets failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    from modules.finance.models import IncomeLog
    db.add(IncomeLog(project=req.project, amount=req.amount, what=req.what,
                     date=today, comment=req.comment))
    db.commit()
    return {"status": "added"}
