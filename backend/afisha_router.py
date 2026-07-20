import io
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from config import AFISHA_DRIVE_FILE_ID, GOOGLE_CALENDAR_JSON

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/afisha", tags=["afisha"])

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 МБ


def _drive_service():
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CALENDAR_JSON, scopes=_DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@router.post("/upload")
async def upload_afisha(file: UploadFile = File(...)):
    if not AFISHA_DRIVE_FILE_ID:
        raise HTTPException(status_code=503, detail="AFISHA_DRIVE_FILE_ID не задан в .env")

    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Файл слишком большой (максимум 20 МБ)")

    mimetype = file.content_type or "application/octet-stream"

    try:
        svc = _drive_service()
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=False)
        svc.files().update(fileId=AFISHA_DRIVE_FILE_ID, media_body=media).execute()
    except Exception as e:
        logger.error("Drive upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Ошибка при загрузке: {e}")

    return {"success": True, "afisha_url": "https://foshoo-theatre.ru/afisha"}
