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
        try:
            result = self.api.get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(title),tables(name,range))"
            ).execute()
            for sheet in result.get("sheets", []):
                if sheet["properties"]["title"] != sheet_name:
                    continue
                for table in sheet.get("tables", []):
                    if table.get("name") == table_name:
                        rng = table.get("range", "")
                        cell = rng.split("!")[1].split(":")[0] if "!" in rng else rng
                        digits = "".join(c for c in cell if c.isdigit())
                        if digits:
                            return int(digits)
        except Exception as e:
            logger.warning(f"Sheets table lookup failed: {e}")
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

    def _sort_table_by_date(self, sheet_id: int, header_row_1based: int,
                             start_col: int, end_col: int, date_col: int) -> None:
        """Сортировать данные таблицы (без заголовка) по дате по убыванию."""
        self.api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{
                "sortRange": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": header_row_1based,  # 0-based = первая строка данных
                        "endRowIndex": 1000,
                        "startColumnIndex": start_col,
                        "endColumnIndex": end_col,
                    },
                    "sortSpecs": [{
                        "dimensionIndex": date_col,
                        "sortOrder": "DESCENDING"
                    }]
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
        """Добавить строку в таблицу Расходы (столбцы A–G)."""
        sheet_id = self._get_sheet_id(self.FINANCE_SHEET)
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Расходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!C:C", "Кто?"))
        # Найти первую пустую строку без вставки строк (INSERT_ROWS/insertDimension
        # сдвигают смежные таблицы на том же листе)
        existing = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!A{header_row + 1}:G1000",
        ).execute().get("values", [])
        new_row = header_row + 1 + len(existing)
        row_data = [project, date, who, amount, what, expense_type, comment]
        self.api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!A{new_row}:G{new_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]},
        ).execute()
        self._sort_table_by_date(sheet_id, header_row, 0, 7, 1)
        logger.info(f"Sheets: added expense {project} {amount} by {who}")

    def add_income(self, project: str, amount: str, what: str, date: str,
                   comment: str = "", income_col_start: str = "O") -> None:
        """Добавить строку в таблицу Доходы (Проект, Сумма, За что?, Дата, Комментарий)."""
        sheet_id = self._get_sheet_id(self.FINANCE_SHEET)
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Доходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!Q:Q", "За что?"))
        income_start_idx = ord(income_col_start) - ord("A")  # O=14
        end_col = chr(ord(income_col_start) + 4)
        # Найти первую пустую строку без вставки строк
        existing = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!{income_col_start}{header_row + 1}:{end_col}1000",
        ).execute().get("values", [])
        new_row = header_row + 1 + len(existing)
        row_data = [project, amount, what, date, comment]
        self.api.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!{income_col_start}{new_row}:{end_col}{new_row}",
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]},
        ).execute()
        self._sort_table_by_date(sheet_id, header_row,
                                  income_start_idx, income_start_idx + 5,
                                  income_start_idx + 3)
        logger.info(f"Sheets: added income {project} {amount}")

    def _delete_table_row(self, sheet_id: int, table_name: str, row_index: int) -> None:
        """Удалить строку внутри именованной таблицы (не трогает соседние таблицы)."""
        self.api.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{"deleteTableRow": {
                "tableRange": {"sheetId": sheet_id, "name": table_name},
                "rowIndex": row_index,
            }}]}
        ).execute()

    def delete_expense_row(self, date_str: str, what: str) -> bool:
        """Найти строку расхода по дате и описанию и удалить её из таблицы Расходы."""
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Расходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!C:C", "Кто?"))
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!A{header_row + 1}:G1000",
        ).execute()
        for i, row in enumerate(result.get("values", [])):
            row_date = row[1].strip() if len(row) > 1 else ""
            row_what = row[4].strip() if len(row) > 4 else ""
            if row_date == date_str and row_what == what:
                sheet_id = self._get_sheet_id(self.FINANCE_SHEET)
                self._delete_table_row(sheet_id, "Расходы", i)
                logger.info(f"Sheets: deleted expense row (table index {i})")
                return True
        return False

    def delete_income_row(self, date_str: str, what: str) -> bool:
        """Найти строку дохода по дате и описанию и удалить её из таблицы Доходы."""
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Доходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!Q:Q", "За что?"))
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!O{header_row + 1}:S1000",
        ).execute()
        for i, row in enumerate(result.get("values", [])):
            row_what = row[2].strip() if len(row) > 2 else ""
            row_date = row[3].strip() if len(row) > 3 else ""
            if row_date == date_str and row_what == what:
                sheet_id = self._get_sheet_id(self.FINANCE_SHEET)
                self._delete_table_row(sheet_id, "Доходы", i)
                logger.info(f"Sheets: deleted income row (table index {i})")
                return True
        return False

    def get_returns(self) -> list[dict]:
        """Прочитать таблицу Возвраты (Откуда, Кому, Сколько, Дата)."""
        table_range = None
        try:
            result = self.api.get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(title),tables(name,range))"
            ).execute()
            for sheet in result.get("sheets", []):
                if sheet["properties"]["title"] != self.FINANCE_SHEET:
                    continue
                for table in sheet.get("tables", []):
                    if table.get("name") == "Возвраты":
                        table_range = table.get("range", "")
                        break
        except Exception as e:
            logger.warning(f"get_returns table lookup failed: {e}")
            return []

        if not table_range:
            logger.warning("Возвраты table not found in sheet metadata")
            return []

        # API может вернуть GridRange dict вместо A1-строки
        if isinstance(table_range, dict):
            sr = table_range.get('startRowIndex', 0) + 1
            er = table_range.get('endRowIndex', 1000)
            sc = _col_num_to_letter(table_range.get('startColumnIndex', 0) + 1)
            ec = _col_num_to_letter(table_range.get('endColumnIndex', 1))
            table_range = f"{self.FINANCE_SHEET}!{sc}{sr}:{ec}{er}"

        rows = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=table_range,
        ).execute().get("values", [])

        items = []
        for row in rows:
            if not row or row[0].strip().lower() in ("откуда", ""):
                continue
            project = row[0].strip() if len(row) > 0 else ""
            who     = row[1].strip() if len(row) > 1 else ""
            amount  = row[2].strip() if len(row) > 2 else ""
            date    = row[3].strip() if len(row) > 3 else ""
            if not project or not amount:
                continue
            items.append({"project": project, "who": who, "amount": amount, "date": date})
        return items

    def get_expenses(self) -> list[dict]:
        """Прочитать все строки таблицы Расходы (A–G)."""
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Расходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!C:C", "Кто?"))
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!A{header_row + 1}:G1000",
        ).execute()
        items = []
        for row in result.get("values", []):
            project      = row[0].strip() if len(row) > 0 else ""
            date         = row[1].strip() if len(row) > 1 else ""
            who          = row[2].strip() if len(row) > 2 else ""
            amount       = row[3].strip() if len(row) > 3 else ""
            what         = row[4].strip() if len(row) > 4 else ""
            expense_type = row[5].strip() if len(row) > 5 else ""
            comment      = row[6].strip() if len(row) > 6 else ""
            if not project or not amount:
                continue
            items.append({"project": project, "date": date, "who": who,
                          "amount": amount, "what": what,
                          "expense_type": expense_type, "comment": comment})
        return items

    def get_incomes(self, income_col_start: str = "O") -> list[dict]:
        """Прочитать все строки таблицы Доходы (O–S)."""
        end_col = chr(ord(income_col_start) + 4)
        header_row = (self._find_table_header_row(self.FINANCE_SHEET, "Доходы")
                      or self._find_header_row(f"{self.FINANCE_SHEET}!Q:Q", "За что?"))
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.FINANCE_SHEET}!{income_col_start}{header_row + 1}:{end_col}1000",
        ).execute()
        items = []
        for row in result.get("values", []):
            project = row[0].strip() if len(row) > 0 else ""
            amount  = row[1].strip() if len(row) > 1 else ""
            what    = row[2].strip() if len(row) > 2 else ""
            date    = row[3].strip() if len(row) > 3 else ""
            comment = row[4].strip() if len(row) > 4 else ""
            if not project or not amount:
                continue
            items.append({"project": project, "amount": amount, "what": what,
                          "date": date, "comment": comment})
        return items

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

    def check_dates_exist(self, event_dts: list) -> list:
        """Вернуть список datetime из event_dts у которых НЕТ столбца в График [составы]."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SCHEDULE_SHEET}!1:1",
        ).execute()
        headers = result.get("values", [[]])[0]
        parsed = [_parse_header_date(h) for h in headers]

        missing = []
        for dt in event_dts:
            found = any(
                p and p.day == dt.day and p.month == dt.month
                for p in parsed
            )
            if not found:
                missing.append(dt)
        return missing

    def get_show_cast(self, show_name: str) -> list[str]:
        """Уникальные имена актёров для указанного спектакля (столбец C)."""
        result = self.api.values().get(
            spreadsheetId=self.spreadsheet_id,
            range="Составы спектаклей!A:C",
        ).execute()
        actors = set()
        for i, row in enumerate(result.get("values", [])):
            if i == 0:
                continue  # заголовок
            if len(row) >= 3 and row[0].strip() == show_name and row[2].strip():
                actors.add(row[2].strip())
        return list(actors)

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
