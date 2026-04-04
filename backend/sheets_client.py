"""
Google Sheets client — запись явок актёров по результатам опросов.

Структура таблицы:
  Вкладка "График [составы]":
    - Строка 1: заголовки дат вида "[сб] 4 апр 20:00"
    - Столбец A: имена актёров (со строки 3)
    - Ячейки: "да" / "нет"

  Вкладка "Настройки":
    - Столбец A: имя актёра (точно как в "График [составы]")
    - Столбец B: Telegram username (без @)
"""
import re
import logging
from datetime import datetime

from googleapiclient.discovery import build
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MONTH_MAP = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}

SCHEDULE_SHEET = "График [составы]"
SETTINGS_SHEET = "Труппа"


class SheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        self.api = service.spreadsheets()
        self.spreadsheet_id = spreadsheet_id

    def get_actor_mapping(self) -> dict[str, str]:
        """Вернуть {telegram_username_lower: actor_name} из вкладки 'Труппа'.
        Имя — столбец A, Telegram username — столбец J (индекс 9). Строка 1 — заголовок."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SETTINGS_SHEET}!A:J",
        ).execute()
        mapping = {}
        for i, row in enumerate(result.get("values", [])):
            if i == 0:
                continue  # пропускаем заголовок
            if len(row) < 10:
                continue  # нет столбца J
            name = row[0].strip()
            username = row[9].strip().lstrip("@").lower()
            if name and username:
                mapping[username] = name
        return mapping

    def find_actor_row(self, actor_name: str) -> int | None:
        """Найти номер строки (1-based) актёра в 'График [составы]'."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SCHEDULE_SHEET}!A:A",
        ).execute()
        for i, row in enumerate(result.get("values", [])):
            if row and row[0].strip() == actor_name:
                return i + 1
        return None

    def find_date_column(self, event_dt: datetime) -> str | None:
        """Найти букву столбца по дате события (сравниваем день+месяц+время)."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SCHEDULE_SHEET}!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]

        # Сначала ищем точное совпадение по дате + времени
        for col_idx, cell in enumerate(headers):
            parsed = _parse_header_date(cell)
            if parsed and parsed.day == event_dt.day and parsed.month == event_dt.month \
                    and parsed.hour == event_dt.hour and parsed.minute == event_dt.minute:
                return _col_num_to_letter(col_idx + 1)

        # Если не нашли — только по дате
        for col_idx, cell in enumerate(headers):
            parsed = _parse_header_date(cell)
            if parsed and parsed.day == event_dt.day and parsed.month == event_dt.month:
                return _col_num_to_letter(col_idx + 1)

        return None

    def write_attendance(self, row: int, col: str, value: str) -> None:
        """Записать 'да' или 'нет' в ячейку."""
        cell = f"{SCHEDULE_SHEET}!{col}{row}"
        self.api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=cell,
            valueInputOption="RAW",
            body={"values": [[value]]},
        ).execute()
        logger.info(f"Sheets: wrote '{value}' to {col}{row}")

    def record_poll_answer(self, telegram_username: str, event_dt: datetime, answer: str) -> bool:
        """
        Записать ответ актёра в таблицу.
        answer: "yes" → "да", "no" → "нет", "unknown"/"retracted" → очистить ячейку.
        Возвращает True если запись прошла успешно.
        """
        if answer == "yes":
            sheet_value = "да"
        elif answer == "no":
            sheet_value = "нет"
        else:
            sheet_value = ""  # "не знаю" или отзыв голоса → пустая ячейка

        mapping = self.get_actor_mapping()
        actor_name = mapping.get(telegram_username.lower())
        if not actor_name:
            logger.warning(f"Sheets: unknown username @{telegram_username}")
            return False

        row = self.find_actor_row(actor_name)
        if not row:
            logger.warning(f"Sheets: actor '{actor_name}' not found in schedule sheet")
            return False

        col = self.find_date_column(event_dt)
        if not col:
            logger.warning(f"Sheets: date {event_dt} not found in schedule sheet headers")
            return False

        self.write_attendance(row, col, sheet_value)
        return True


def _parse_header_date(cell: str) -> datetime | None:
    """Распарсить '[сб] 4 апр 20:00' → datetime (год не важен, ставим текущий)."""
    cell = re.sub(r"\[.*?\]", "", cell).strip()
    m = re.match(r"(\d+)\s+(\S+)\s+(\d+):(\d+)", cell)
    if not m:
        return None
    day, month_str, hour, minute = m.groups()
    month = MONTH_MAP.get(month_str.lower())
    if not month:
        return None
    try:
        return datetime(datetime.now().year, month, int(day), int(hour), int(minute))
    except ValueError:
        return None


def _col_num_to_letter(n: int) -> str:
    """1 → 'A', 27 → 'AA' и т.д."""
    result = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result
