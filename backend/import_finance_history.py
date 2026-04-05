"""
Одноразовый скрипт импорта истории финансов из Google Sheets в локальную БД.
Запускать из директории backend/:
    python import_finance_history.py
"""
import sys
import os

# Добавить backend/ в путь
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core.database import init_db, SessionLocal
from modules.finance.models import ExpenseLog, IncomeLog, ReturnsLog
from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
from sheets_client import SheetsClient


def _parse_amount(s) -> int:
    cleaned = str(s).replace('р.', '').replace('₽', '').replace('\xa0', '').replace(' ', '').replace(',', '.')
    return round(float(cleaned))


def _dmy_to_iso(s: str) -> str:
    d, m, y = s.strip().split('.')
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def import_expenses(client: SheetsClient, db):
    result = client.api.values().get(
        spreadsheetId=client.spreadsheet_id,
        range="Финансы!A:G",
    ).execute()
    rows = result.get("values", [])

    count = 0
    for row in rows:
        if not row or not row[0].strip():
            continue
        if row[0].strip().lower() in ("проект", "затраты по проектам"):
            continue  # заголовок

        project  = row[0].strip() if len(row) > 0 else ""
        date_str = row[1].strip() if len(row) > 1 else ""
        who      = row[2].strip() if len(row) > 2 else ""
        amount   = row[3].strip() if len(row) > 3 else ""
        what     = row[4].strip() if len(row) > 4 else ""
        etype    = row[5].strip() if len(row) > 5 else ""
        comment  = row[6].strip() if len(row) > 6 else ""

        if not project or not amount:
            continue

        try:
            amount_int = _parse_amount(amount)
        except Exception:
            print(f"  skip expense (bad amount): {amount!r}")
            continue

        try:
            date_iso = _dmy_to_iso(date_str) if date_str else None
        except Exception:
            date_iso = None

        db.add(ExpenseLog(
            project=project, date=date_iso, who=who,
            amount=amount_int, what=what, expense_type=etype, comment=comment,
        ))
        count += 1

    db.commit()
    print(f"Импортировано расходов: {count}")


def import_income(client: SheetsClient, db):
    result = client.api.values().get(
        spreadsheetId=client.spreadsheet_id,
        range="Финансы!O:S",
    ).execute()
    rows = result.get("values", [])

    count = 0
    for row in rows:
        if not row or not row[0].strip():
            continue
        if row[0].strip().lower() == "проект":
            continue  # заголовок

        project = row[0].strip() if len(row) > 0 else ""
        amount  = row[1].strip() if len(row) > 1 else ""
        what    = row[2].strip() if len(row) > 2 else ""
        date_str = row[3].strip() if len(row) > 3 else ""
        comment = row[4].strip() if len(row) > 4 else ""

        if not project or not amount:
            continue

        try:
            amount_int = _parse_amount(amount)
        except Exception:
            print(f"  skip income (bad amount): {amount!r}")
            continue

        try:
            date_iso = _dmy_to_iso(date_str) if date_str else None
        except Exception:
            date_iso = None

        db.add(IncomeLog(
            project=project, amount=amount_int, what=what,
            date=date_iso, comment=comment,
        ))
        count += 1

    db.commit()
    print(f"Импортировано доходов: {count}")


def import_returns(client: SheetsClient, db):
    rows = client.get_returns()
    count = 0
    for r in rows:
        try:
            amount_int = _parse_amount(r["amount"]) if r["amount"] else 0
        except Exception:
            amount_int = 0
        try:
            date_iso = _dmy_to_iso(r["date"]) if r["date"] else None
        except Exception:
            date_iso = None
        db.add(ReturnsLog(
            project=r["project"], who=r["who"],
            amount=amount_int, date=date_iso,
        ))
        count += 1
    db.commit()
    print(f"Импортировано возвратов: {count}")


if __name__ == "__main__":
    if not GOOGLE_SHEETS_ID:
        print("GOOGLE_SHEETS_ID не задан в .env")
        sys.exit(1)

    init_db()
    db = SessionLocal()

    # Проверить что таблицы пустые чтобы не дублировать
    if db.query(ExpenseLog).count() > 0 or db.query(IncomeLog).count() > 0:
        print("В БД уже есть записи. Запустить повторно? (yes/no)")
        if input().strip().lower() != "yes":
            print("Отменено.")
            db.close()
            sys.exit(0)

    client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
    import_expenses(client, db)
    import_income(client, db)
    import_returns(client, db)

    db.close()
    print("Готово.")
