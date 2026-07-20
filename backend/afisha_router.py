import io
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from config import AFISHA_NEW_DRIVE_FILE_ID, AFISHA_OLD_DRIVE_FILE_ID, GOOGLE_CALENDAR_JSON

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/afisha", tags=["afisha"])

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 МБ


def _drive_service():
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CALENDAR_JSON, scopes=_DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _download_file(svc, file_id: str) -> tuple[bytes, str]:
    meta = svc.files().get(fileId=file_id, fields="mimeType").execute()
    mimetype = meta.get("mimeType", "application/octet-stream")
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue(), mimetype


def _upload_bytes(svc, file_id: str, content: bytes, mimetype: str) -> None:
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=False)
    svc.files().update(fileId=file_id, media_body=media).execute()


@router.post("/upload")
async def upload_afisha(file: UploadFile = File(...)):
    if not AFISHA_NEW_DRIVE_FILE_ID or not AFISHA_OLD_DRIVE_FILE_ID:
        raise HTTPException(status_code=503, detail="AFISHA_*_DRIVE_FILE_ID не задан в .env")

    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Файл слишком большой (максимум 20 МБ)")

    mimetype = file.content_type or "application/octet-stream"

    try:
        svc = _drive_service()
        # Сдвиг: afisha-new → afisha-old
        old_content, old_mime = _download_file(svc, AFISHA_NEW_DRIVE_FILE_ID)
        _upload_bytes(svc, AFISHA_OLD_DRIVE_FILE_ID, old_content, old_mime)
        # Новый файл → afisha-new
        _upload_bytes(svc, AFISHA_NEW_DRIVE_FILE_ID, content, mimetype)
    except Exception as e:
        logger.error("Drive upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Ошибка при загрузке: {e}")

    return {"success": True, "afisha_url": "https://foshoo-theatre.ru/afisha"}
