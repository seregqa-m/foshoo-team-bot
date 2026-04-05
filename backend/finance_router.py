import logging
import os
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from modules.finance.models import ExpenseLog, IncomeLog, ReturnsLog  # noqa: F401 — ensure tables are created on init_db()

router = APIRouter(prefix="/api/finance", tags=["finance"])
logger = logging.getLogger(__name__)

EXPENSE_TYPES = ["Личные траты", "Трата со счета ФоШу", "Пожертвование"]
PROJECTS = ["Театр", "Любовь Громова", "Урод", "Слепые"]


# ── Вспомогательные функции ──────────────────────────────────────────────────

def _parse_amount(s) -> int:
    """'р.30 000,00' → 30000"""
    cleaned = str(s).replace('р.', '').replace('₽', '').replace('\xa0', '').replace(' ', '').replace(',', '.')
    return round(float(cleaned))


def _amt(v) -> int:
    """Безопасно привести значение из БД к int (защита от строк при смешанных типах)."""
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    return _parse_amount(v)


def _dmy_to_iso(s: str) -> str:
    """'15.01.2024' → '2024-01-15'"""
    d, m, y = s.strip().split('.')
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def _iso_to_dmy(s: str) -> str:
    """'2024-01-15' → '15.01.2024'"""
    y, m, d = s.strip().split('-')
    return f"{d}.{m}.{y}"


# ── Google Sheets клиент ─────────────────────────────────────────────────────

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


# ── Эндпоинты ────────────────────────────────────────────────────────────────

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
    today_dmy = req.date.strip() if req.date.strip() else date.today().strftime("%d.%m.%Y")
    today_iso = _dmy_to_iso(today_dmy)

    try:
        client = _get_client()
        client.add_expense(req.project, today_dmy, who, req.amount, req.what, req.expense_type, req.comment)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_expense sheets failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    db.add(ExpenseLog(
        project=req.project, date=today_iso, who=who,
        amount=_parse_amount(req.amount),
        what=req.what, expense_type=req.expense_type, comment=req.comment,
    ))
    db.commit()
    return {"status": "added"}


@router.get("/chart")
async def get_chart(period: str = "month", from_date: str = None, db: Session = Depends(get_db)):
    """
    period=month: доходы/расходы по месяцам с разбивкой по типу расхода.
    period=day:   P&L — ФоШу-траты + Возвраты, полный период, нарастающим итогом.
    """
    from collections import defaultdict

    if period == "day":
        income_agg: dict[str, int] = defaultdict(int)
        expense_agg: dict[str, int] = defaultdict(int)

        for row in db.query(IncomeLog).all():
            if row.date and row.amount is not None:
                income_agg[row.date] += _amt(row.amount)

        for row in db.query(ExpenseLog).filter(ExpenseLog.expense_type == "Трата со счета ФоШу").all():
            if row.date and row.amount is not None:
                expense_agg[row.date] += _amt(row.amount)

        for row in db.query(ReturnsLog).all():
            if row.date and row.amount is not None:
                expense_agg[row.date] += _amt(row.amount)

        all_dates = set(income_agg) | set(expense_agg)
        if not all_dates:
            return {"data": []}

        valid = sorted(d for d in all_dates if d)
        start = date.fromisoformat(valid[0])
        today_date = date.today()
        all_keys, cur = [], start
        while cur <= today_date:
            all_keys.append(cur.isoformat())
            cur += timedelta(days=1)

        data = [
            {"period": _iso_to_dmy(k), "income": income_agg.get(k, 0), "expense": expense_agg.get(k, 0)}
            for k in all_keys
        ]
        return {"data": data}

    # period == "month"
    def month_key(date_str: str) -> str | None:
        if not date_str:
            return None
        try:
            y, m, _ = date_str.strip().split("-")
            return f"{m}.{y}"
        except Exception:
            return None

    def month_sort(label: str) -> tuple:
        try:
            m, y = label.split(".")
            return (int(y), int(m))
        except Exception:
            return (0, 0)

    from_iso = _dmy_to_iso(from_date) if from_date else None

    income_agg: dict[str, int] = defaultdict(int)
    exp_foshu: dict[str, int] = defaultdict(int)
    exp_personal: dict[str, int] = defaultdict(int)
    exp_donation: dict[str, int] = defaultdict(int)

    for row in db.query(IncomeLog).all():
        if from_iso and row.date and row.date < from_iso:
            continue
        k = month_key(row.date)
        if k and row.amount is not None:
            income_agg[k] += _amt(row.amount)

    for row in db.query(ExpenseLog).all():
        if from_iso and row.date and row.date < from_iso:
            continue
        k = month_key(row.date)
        if not k or row.amount is None:
            continue
        amt = _amt(row.amount)
        if row.expense_type == "Трата со счета ФоШу":
            exp_foshu[k] += amt
        elif row.expense_type == "Личные траты":
            exp_personal[k] += amt
        elif row.expense_type in ("Пожертвование", "Пожертвования"):
            exp_donation[k] += amt
        else:
            exp_foshu[k] += amt

    for row in db.query(ReturnsLog).all():
        if from_iso and row.date and row.date < from_iso:
            continue
        k = month_key(row.date)
        if k and row.amount is not None:
            exp_foshu[k] += _amt(row.amount)

    all_keys = sorted(
        set(income_agg) | set(exp_foshu) | set(exp_personal) | set(exp_donation),
        key=month_sort
    )
    data = [
        {
            "period": k,
            "income": income_agg[k],
            "expense_foshu": exp_foshu[k],
            "expense_personal": exp_personal[k],
            "expense_donation": exp_donation[k],
            "expense": exp_foshu[k] + exp_personal[k] + exp_donation[k],
        }
        for k in all_keys
    ]
    return {"data": data}


@router.post("/sync-returns")
async def sync_returns(db: Session = Depends(get_db)):
    """Синхронизировать таблицу Возвраты из Google Sheets."""
    try:
        client = _get_client()
        rows = client.get_returns()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.query(ReturnsLog).delete()
    for r in rows:
        db.add(ReturnsLog(
            project=r["project"], who=r["who"],
            amount=_parse_amount(r["amount"]) if r["amount"] else 0,
            date=_dmy_to_iso(r["date"]) if r["date"] else None,
        ))
    db.commit()
    return {"status": "synced", "count": len(rows)}


@router.get("/transactions")
async def get_transactions(limit: int = 10, db: Session = Depends(get_db)):
    """Последние N операций (доходы + расходы) из БД, отсортированные по дате."""
    items = []
    for e in db.query(ExpenseLog).all():
        items.append({
            "id": e.id, "type": "expense",
            "date": _iso_to_dmy(e.date) if e.date else "",
            "_iso": e.date or "",
            "amount": str(e.amount) if e.amount is not None else "0",
            "what": e.what, "project": e.project, "who": e.who,
            "expense_type": e.expense_type, "comment": e.comment or "",
            "created_at": e.created_at.isoformat() if e.created_at else "",
        })
    for i in db.query(IncomeLog).all():
        items.append({
            "id": i.id, "type": "income",
            "date": _iso_to_dmy(i.date) if i.date else "",
            "_iso": i.date or "",
            "amount": str(i.amount) if i.amount is not None else "0",
            "what": i.what, "project": i.project, "who": "",
            "expense_type": "", "comment": i.comment or "",
            "created_at": i.created_at.isoformat() if i.created_at else "",
        })

    items.sort(key=lambda x: x["_iso"], reverse=True)
    for item in items:
        del item["_iso"]
    return {"transactions": items[:limit]}


@router.delete("/transactions/{tx_type}/{tx_id}")
async def delete_transaction(tx_type: str, tx_id: int, db: Session = Depends(get_db)):
    """Удалить операцию из БД и Google Sheets."""
    if tx_type == "expense":
        row = db.query(ExpenseLog).filter(ExpenseLog.id == tx_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            _get_client().delete_expense_row(_iso_to_dmy(row.date) if row.date else "", row.what)
        except Exception as e:
            logger.warning(f"Sheets delete expense failed: {e}")
        db.delete(row)
    elif tx_type == "income":
        row = db.query(IncomeLog).filter(IncomeLog.id == tx_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            _get_client().delete_income_row(_iso_to_dmy(row.date) if row.date else "", row.what)
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

    today_dmy = req.date.strip() if req.date.strip() else date.today().strftime("%d.%m.%Y")
    today_iso = _dmy_to_iso(today_dmy)

    try:
        client = _get_client()
        client.add_income(req.project, req.amount, req.what, today_dmy, req.comment)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_income sheets failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    db.add(IncomeLog(
        project=req.project, amount=_parse_amount(req.amount),
        what=req.what, date=today_iso, comment=req.comment,
    ))
    db.commit()
    return {"status": "added"}
