import logging
import os
from fastapi import APIRouter

router = APIRouter(prefix="/api/sheets", tags=["sheets"])
logger = logging.getLogger(__name__)


@router.get("/shows")
async def get_show_names():
    """Вернуть список названий спектаклей Труппы 1 из Google Sheets."""
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient

    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"shows": []}

    try:
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        return {"shows": client.get_show_names()}
    except Exception as e:
        logger.error(f"get_show_names failed: {e}")
        return {"shows": []}
