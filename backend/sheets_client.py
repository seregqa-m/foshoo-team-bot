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

    def read_cell(self, row: int, col: str) -> str:
        """Прочитать текущее значение ячейки."""
        cell = f"{SCHEDULE_SHEET}!{col}{row}"
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=cell,
        ).execute()
        rows = result.get("values", [])
        return rows[0][0].strip() if rows and rows[0] else ""

    def write_attendance(self, row: int, col: str, value: str) -> None:
        """Записать 'да' или 'нет' в ячейку.
        Пропускает запись если в ячейке уже стоит название роли."""
        current = self.read_cell(row, col)
        if current.lower() not in ("да", "нет", ""):
            logger.info(f"Sheets: skip {col}{row} — has role value '{current}'")
            return
        cell = f"{SCHEDULE_SHEET}!{col}{row}"
        self.api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=cell,
            valueInputOption="RAW",
            body={"values": [[value]]},
        ).execute()
        logger.info(f"Sheets: wrote '{value}' to {col}{row}")

    # ── Финансы ──────────────────────────────────────────────────────────

    FINANCE_SHEET = "Финансы"
    EXPENSE_TYPES = ["Личные траты", "Трата со счета ФоШу", "Пожертвование"]
    PROJECTS = ["Театр", "Любовь Громова", "Урод", "Слепые"]

    def _get_sheet_id(self, sheet_name: str) -> int:
        """Получить числовой ID листа по имени."""
        result = self.api.get(spreadsheetId=self.spreadsheet_id).execute()
        for sheet in result["sheets"]:
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
        raise ValueError(f"Sheet '{sheet_name}' not found")

    def _find_table_header_row(self, sheet_name: str, table_name: str) -> int | None:
        """Найти 1-based строку заголовка именованной таблицы через метаданные Sheets API."""
        result = self.api.get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(title),tables(name,range))"
        ).execute()
        for sheet in result.get("sheets", []):
            if sheet["properties"]["title"] != sheet_name:
                continue
            for table in sheet.get("tables", []):
                if table.get("name") == table_name:
                    # range вида "Финансы!A10:G100"
                    rng = table.get("range", "")
                    cell = rng.split("!")[1].split(":")[0] if "!" in rng else rng
                    # извлечь номер строки из ячейки типа "A10"
                    row_num = int("".join(c for c in cell if c.isdigit()))
                    return row_num
        return None

    def _find_header_row(self, col_range: str, search_value: str = "Проект") -> int:
        """Найти 1-based номер строки с заданным значением в указанном диапазоне (fallback)."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=col_range,
        ).execute()
        for i, row in enumerate(result.get("values", [])):
            if row and row[0].strip() == search_value:
                return i + 1
        return 1

    def _insert_row_after_header(self, sheet_id: int, header_row_1based: int) -> None:
        """Вставить пустую строку сразу после заголовка."""
        self.api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": header_row_1based,   # 0-based = сразу после header
                        "endIndex": header_row_1based + 1,
                    },
                    "inheritFromBefore": False,
                }
            }]}
        ).execute()

    def get_balance(self) -> str:
        """Прочитать остаток копилки из ячейки G4."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!G4",
        ).execute()
        rows = result.get("values", [])
        return rows[0][0].strip() if rows and rows[0] else "—"

    def add_expense(self, project: str, date: str, who: str,
                    amount: str, what: str, expense_type: str, comment: str = "") -> None:
        """Добавить строку в начало таблицы Расходы (столбцы A–G)."""
        sheet_id = self._get_sheet_id(self.FINANCE_SHEET)
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Расходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!C:C", "Кто?"))
        self._insert_row_after_header(sheet_id, header_row)
        new_row = header_row + 1
        self.api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!A{new_row}:G{new_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [[project, date, who, amount, what, expense_type, comment]]},
        ).execute()
        logger.info(f"Sheets: added expense {project} {amount} by {who}")

    def add_income(self, project: str, amount: str, what: str, date: str,
                   comment: str = "", income_col_start: str = "O") -> None:
        """Добавить строку в начало таблицы Доходы (Проект, Сумма, За что?, Дата, Комментарий)."""
        sheet_id = self._get_sheet_id(self.FINANCE_SHEET)
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Доходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!Q:Q", "За что?"))
        self._insert_row_after_header(sheet_id, header_row)
        new_row = header_row + 1
        end_col = chr(ord(income_col_start) + 4)
        self.api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!{income_col_start}{new_row}:{end_col}{new_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [[project, amount, what, date, comment]]},
        ).execute()
        logger.info(f"Sheets: added income {project} {amount}")

    def get_show_names(self) -> list[str]:
        """Уникальные названия спектаклей из вкладки 'Составы спектаклей', столбец A."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range="Составы спектаклей!A:A",
        ).execute()
        names = set()
        for i, row in enumerate(result.get("values", [])):
            if i == 0:
                continue  # заголовок
            if row and row[0].strip():
                names.add(row[0].strip())
        return list(names)

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
