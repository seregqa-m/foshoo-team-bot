import logging
import os
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/finance", tags=["finance"])
logger = logging.getLogger(__name__)

EXPENSE_TYPES = ["Личные траты", "Трата со счета ФоШу", "Пожертвование"]
PROJECTS = ["Театр", "ЛГ", "Урод", "Слепые"]


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
    """Вернуть списки проектов и типов трат для форм."""
    return {"projects": PROJECTS, "expense_types": EXPENSE_TYPES}


class ExpenseRequest(BaseModel):
    project: str
    amount: str
    what: str
    expense_type: str
    comment: str = ""
    username: str = ""  # Telegram username для автозаполнения Кто


class IncomeRequest(BaseModel):
    project: str
    amount: str
    what: str
    comment: str = ""


@router.post("/expense")
async def add_expense(req: ExpenseRequest):
    if req.project not in PROJECTS:
        raise HTTPException(status_code=400, detail="Неверный проект")
    if req.expense_type not in EXPENSE_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип траты")

    who = _resolve_name(req.username) if req.username else "—"
    today = date.today().strftime("%d.%m.%Y")

    try:
        client = _get_client()
        client.add_expense(req.project, today, who, req.amount, req.what, req.expense_type, req.comment)
        return {"status": "added"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_expense failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/income")
async def add_income(req: IncomeRequest):
    if req.project not in PROJECTS:
        raise HTTPException(status_code=400, detail="Неверный проект")

    today = date.today().strftime("%d.%m.%Y")

    try:
        client = _get_client()
        client.add_income(req.project, req.amount, req.what, today, req.comment)
        return {"status": "added"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"add_income failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
