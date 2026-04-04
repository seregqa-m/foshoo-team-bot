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
    actors = []
    try:
        client = _get_client()
        mapping = client.get_actor_mapping()
        actors = sorted(mapping.values())
    except Exception:
        pass
    return {"projects": PROJECTS, "expense_types": EXPENSE_TYPES, "actors": actors}


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


class IncomeRequest(BaseModel):
    project: str
    amount: str
    what: str
    comment: str = ""


@router.post("/expense")
async def add_expense(req: ExpenseRequest, db: Session = Depends(get_db)):
    if req.project not in PROJECTS:
        raise HTTPException(status_code=400, detail="Неверный проект")
    if req.expense_type not in EXPENSE_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип траты")

    who = req.who.strip() if req.who.strip() else (_resolve_name(req.username) if req.username else "—")
    today = date.today().strftime("%d.%m.%Y")

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
    Агрегация доходов/расходов по месяцам (period=month) или дням (period=day, последние 60 дней).
    Даты хранятся в формате dd.mm.yyyy.
    """
    from modules.finance.models import ExpenseLog, IncomeLog
    from collections import defaultdict

    def parse_key(date_str: str) -> str | None:
        try:
            parts = date_str.strip().split(".")
            if len(parts) != 3:
                return None
            d, m, y = parts
            if period == "month":
                return f"{m}.{y}"
            else:
                return date_str
        except Exception:
            return None

    def sort_key(label: str) -> tuple:
        try:
            parts = label.split(".")
            if period == "month":
                return (int(parts[1]), int(parts[0]))
            else:
                return (int(parts[2]), int(parts[1]), int(parts[0]))
        except Exception:
            return (0,)

    expense_agg: dict[str, float] = defaultdict(float)
    income_agg: dict[str, float] = defaultdict(float)

    def date_tuple(s: str) -> tuple:
        try:
            d, m, y = s.strip().split(".")
            return (int(y), int(m), int(d))
        except Exception:
            return (0, 0, 0)

    from_tuple = date_tuple(from_date) if from_date else None

    def parse_amount(raw) -> float:
        s = str(raw).replace("р.", "").replace("₽", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        return float(s)

    for row in db.query(ExpenseLog).all():
        if from_tuple and date_tuple(row.date) < from_tuple:
            continue
        key = parse_key(row.date)
        if key:
            try:
                expense_agg[key] += parse_amount(row.amount)
            except (ValueError, TypeError):
                pass

    for row in db.query(IncomeLog).all():
        if from_tuple and date_tuple(row.date) < from_tuple:
            continue
        key = parse_key(row.date)
        if key:
            try:
                income_agg[key] += parse_amount(row.amount)
            except (ValueError, TypeError):
                pass

    if period == "day":
        # Генерируем все дни от from_date (или 60 дней назад) до сегодня
        if from_date:
            d_parts = from_date.strip().split(".")
            start = date(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]))
        else:
            start = date.today() - timedelta(days=59)
        today_date = date.today()
        all_keys = []
        cur = start
        while cur <= today_date:
            all_keys.append(cur.strftime("%d.%m.%Y"))
            cur += timedelta(days=1)
    else:
        all_keys = sorted(set(expense_agg) | set(income_agg), key=sort_key)

    data = [
        {"period": k, "income": round(income_agg[k]), "expense": round(expense_agg[k])}
        for k in all_keys
    ]
    return {"data": data}


@router.post("/income")
async def add_income(req: IncomeRequest, db: Session = Depends(get_db)):
    if req.project not in PROJECTS:
        raise HTTPException(status_code=400, detail="Неверный проект")

    today = date.today().strftime("%d.%m.%Y")

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
