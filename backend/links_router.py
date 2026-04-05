import json
import os
from fastapi import APIRouter

router = APIRouter(prefix="/api/links", tags=["links"])

LINKS_FILE = os.path.join(os.path.dirname(__file__), "links.json")


@router.get("")
async def get_links():
    """Вернуть блоки ссылок из links.json."""
    if not os.path.exists(LINKS_FILE):
        return {"blocks": []}
    with open(LINKS_FILE, encoding="utf-8") as f:
        return json.load(f)
