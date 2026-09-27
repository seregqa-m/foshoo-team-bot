import os
import unittest
from unittest.mock import patch, MagicMock

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://"}, clear=True), patch("dotenv.load_dotenv"):
    import finance_router as finance
    from modules.finance.models import ExpenseLog, IncomeLog
    from modules.assistant.context import FINANCE_PROJECTS
    from sheets_client import SheetsClient

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FinanceProjectTests(unittest.TestCase):
    def test_new_project_available_and_written_to_sheets_and_database(self):
        project = "Цианистый калий"
        engine = create_engine("sqlite://")
        ExpenseLog.__table__.create(engine)
        IncomeLog.__table__.create(engine)
        client = MagicMock()
        client.get_actor_mapping.return_value = {}
        try:
            with Session(engine) as db, patch("finance_router._get_client", return_value=client):
                self.assertIn(project, finance.get_meta()["projects"])
                self.assertIn(project, FINANCE_PROJECTS)
                self.assertIn(project, SheetsClient.PROJECTS)
                finance.add_expense(finance.ExpenseRequest(
                    project=project, amount="100", what="Реквизит", who="Актёр",
                    expense_type="Личные траты", date="27.09.2026"), db)
                finance.add_income(finance.IncomeRequest(
                    project=project, amount="200", what="Билеты", date="27.09.2026"), db)
                self.assertEqual(client.add_expense.call_args.args[0], project)
                self.assertEqual(client.add_income.call_args.args[0], project)
                self.assertEqual(db.query(ExpenseLog).one().project, project)
                self.assertEqual(db.query(IncomeLog).one().project, project)
        finally:
            engine.dispose()
