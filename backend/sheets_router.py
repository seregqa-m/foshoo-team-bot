import logging
import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from modules.theater.routing import show_aliases

router = APIRouter(prefix="/api/sheets", tags=["sheets"])
logger = logging.getLogger(__name__)


@router.get("/shows")
def get_show_names(db: Session = Depends(get_db)):
    """Вернуть список названий спектаклей Труппы 1 из Google Sheets."""
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient

    aliases = show_aliases(db)
    names = {show.name for show in aliases.values()}
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"shows": sorted(names)}

    try:
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        from modules.theater.services import normalize_name
        names.update(aliases[normalize_name(name)].name if normalize_name(name) in aliases else name
                     for name in client.get_show_names())
        return {"shows": sorted(names)}
    except Exception as e:
        logger.error(f"get_show_names failed: {e}")
        return {"shows": sorted(names)}
