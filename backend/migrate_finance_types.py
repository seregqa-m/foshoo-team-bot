"""
Одноразовая миграция: конвертировать строковые amounts → int,
даты DD.MM.YYYY → ISO YYYY-MM-DD во всех финансовых таблицах.

Запускать из директории backend/:
    python migrate_finance_types.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from core.database import init_db, SessionLocal
from modules.finance.models import ExpenseLog, IncomeLog, ReturnsLog


def parse_amt(s) -> int:
    cleaned = str(s).replace('р.', '').replace('₽', '').replace('\xa0', '').replace(' ', '').replace(',', '.')
    return round(float(cleaned))


def to_iso(s) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    if len(s) == 10 and '-' in s:
        return s  # уже ISO
    parts = s.split('.')
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return s


if __name__ == "__main__":
    from sqlalchemy import text
    from core.database import engine

    init_db()

    # Шаг 1: через ORM — конвертируем сложные строки вида "р.30 000,00" и даты DD.MM.YYYY
    db = SessionLocal()
    changed = 0
    errors = 0

    for Model in [ExpenseLog, IncomeLog, ReturnsLog]:
        for row in db.query(Model).all():
            if isinstance(row.amount, str):
                try:
                    row.amount = parse_amt(row.amount)
                    changed += 1
                except Exception as e:
                    print(f"  [WARN] bad amount {row.amount!r} in {Model.__tablename__} id={row.id}: {e}")
                    errors += 1

            new_date = to_iso(row.date)
            if new_date != row.date:
                row.date = new_date
                changed += 1

    db.commit()
    db.close()
    print(f"ORM: {changed} значений конвертировано, ошибок: {errors}")

    # Шаг 2: через raw SQL — принудительно приводим TEXT "30000" → INTEGER
    # (SQLAlchemy читает их как int, поэтому ORM их не трогает)
    sql_changed = 0
    with engine.connect() as conn:
        for table in ['expense_log', 'income_log', 'returns_log']:
            result = conn.execute(text(
                f"UPDATE {table} SET amount = CAST(amount AS INTEGER) WHERE typeof(amount) = 'text'"
            ))
            sql_changed += result.rowcount
        conn.commit()
    print(f"SQL: {sql_changed} текстовых amount приведено к INTEGER")
    print("Готово.")
