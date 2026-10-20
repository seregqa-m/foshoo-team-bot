import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {"BOT_TOKEN": "123456:offline-test-token", "DATABASE_URL": "sqlite://"},
                clear=True), patch("dotenv.load_dotenv"):
    import finance_router as finance
    from modules.finance.models import ExpenseLog, IncomeLog, ReturnsLog
    from modules.finance.reconciliation import fingerprint, reconcile, row_values

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FinanceReimbursementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        for model in (ExpenseLog, IncomeLog, ReturnsLog):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        clock = patch("finance_router.local_now", return_value=datetime(2026, 10, 20, 12))
        clock.start()
        self.addCleanup(clock.stop)

    def expense(self, who, amount, kind="Личные траты", **kwargs):
        values = dict(who=who, amount=amount, expense_type=kind, project="Театр",
                      date="2026-10-20", what="Реквизит")
        row = ExpenseLog(**(values | kwargs))
        self.db.add(row)
        self.db.commit()
        return row

    def test_all_time_personal_costs_minus_refunds_excludes_bank_donations_and_income(self):
        self.expense("Анна Иванова", 500, date="2020-01-01")
        self.expense("Анна Иванова", 700, project="Урод")
        self.expense("Анна Иванова", 200, "Возврат")
        self.expense("Анна Иванова", 20000, finance.BANK_EXPENSE)
        self.expense("Анна Иванова", 30000, "Пожертвование")
        self.db.add(IncomeLog(amount=100000))
        # Legacy cache must not double count an already migrated refund.
        self.db.add(ReturnsLog(who="Анна Иванова", amount=200))
        self.db.commit()
        result = finance.get_reimbursements(self.db)
        self.assertEqual(result["total"], 1000)
        self.assertEqual(result["people"], [
            dict(who="Анна Иванова", personal=1200, returned=200, amount=1000)])

    def test_fully_paid_and_overpaid_people_do_not_reduce_someone_elses_debt(self):
        self.expense("Анна", 500)
        self.expense("Анна", 500, "Возврат")
        self.expense("Борис", 200)
        self.expense("Борис", 1000, "Возврат")
        self.expense("Вера", 600)
        self.expense("Глеб", 700)
        result = finance.get_reimbursements(self.db)
        self.assertEqual(result["total"], 1300)
        self.assertEqual([p["who"] for p in result["people"]], ["Глеб", "Вера"])

    def test_names_normalize_spacing_and_case_but_do_not_guess_aliases(self):
        self.expense(" Анна  Иванова ", 500)
        self.expense("анна\u00a0иванова", 200, "Возврат")
        self.expense("Аня Иванова", 100)
        result = finance.get_reimbursements(self.db)
        self.assertEqual([(p["who"], p["amount"]) for p in result["people"]],
                         [("Анна Иванова", 300), ("Аня Иванова", 100)])

    def test_anonymous_refunds_are_flagged_and_never_assigned_to_a_person(self):
        self.expense(None, 500)
        self.expense("—", 100, "Возврат")
        self.expense("Анна", 200)
        result = finance.get_reimbursements(self.db)
        self.assertEqual(result["total"], 700)
        self.assertEqual(result["unassigned"], {"personal": 500, "returned": 100})
        self.assertEqual(result["people"][0]["amount"], 200)

    def test_empty_ledger_has_no_debt(self):
        self.assertEqual(finance.get_reimbursements(self.db),
                         dict(total=0, people=[], unassigned=dict(personal=0, returned=0),
                              recent=dict(total=0, people=[], unassigned=dict(personal=0, returned=0),
                                          from_date="2026-09-21", to_date="2026-10-20")))

    def test_last_30_days_inclusive_excludes_old_future_and_unknown_dates(self):
        for day, amount in [("2026-09-20", 1000), ("2026-09-21", 200),
                            ("20.10.2026", 400), ("2026-10-21", 2000),
                            (None, 3000), ("invalid", 4000), ("2026-99-99", 5000)]:
            self.expense("Анна", amount, date=day)
        self.expense("анна", 50, "Возврат", date="2026-10-20")
        self.expense("Анна", 75, "Возврат", date="2026-09-20")
        self.expense("Анна", 9000, finance.BANK_EXPENSE)
        result = finance.get_reimbursements(self.db)
        self.assertEqual(result["recent"]["total"], 550)
        self.assertEqual(result["recent"]["people"], [
            dict(who="Анна", personal=600, returned=50, amount=550)])
        self.assertEqual(result["total"], 15475)

    def test_recent_refund_of_old_debt_does_not_reduce_other_person_or_become_negative(self):
        self.expense("Анна", 1000, date="2020-01-01")
        self.expense("Анна", 300, "Возврат")
        self.expense("Борис", 200)
        self.expense(None, 100)
        self.expense("—", 400, "Возврат")
        result = finance.get_reimbursements(self.db)
        self.assertEqual(result["total"], 1000)
        self.assertEqual(result["recent"]["total"], 300)
        self.assertEqual([p["who"] for p in result["recent"]["people"]], ["Борис"])
        self.assertEqual(result["recent"]["unassigned"], dict(personal=100, returned=400))

    def test_history_is_complete_mixed_newest_first_and_uses_normalized_identity(self):
        self.expense(" Анна  Иванова ", 200, date="2020-01-01")
        refund = self.expense("анна\u00a0иванова", 50, "Возврат", date="20.10.2026")
        newest = self.expense("Анна Иванова", 100, date="2026-10-20", comment="Комментарий")
        self.expense("Анна Иванова", 300, finance.BANK_EXPENSE)
        self.expense("Анна Иванова", 300, "Пожертвование")
        self.expense("Аня Иванова", 900)
        for _ in range(12):
            self.expense("Анна Иванова", 10, date="2021-01-01")
        unknown = self.expense("Анна Иванова", 20, date=None)
        rows = finance.get_reimbursement_history(" анна Иванова ", self.db)["transactions"]
        self.assertEqual(len(rows), 16)
        self.assertEqual([r["id"] for r in rows[:2]], [newest.id, refund.id])
        self.assertEqual(rows[0]["comment"], "Комментарий")
        self.assertEqual(rows[1]["expense_type"], "Возврат")
        self.assertEqual(rows[1]["date"], "2026-10-20")
        self.assertEqual(rows[-1]["id"], unknown.id)
        self.assertEqual(finance.get_reimbursement_history("Нет такого", self.db), dict(transactions=[]))

    def test_historical_bank_label_keeps_original_fingerprint_and_deletion_match(self):
        row = self.expense("Дарья Шарыгина", 500, finance.BANK_EXPENSE)
        original = row_values(row)
        transaction = finance.get_transactions(db=self.db)["transactions"][0]
        self.assertEqual(transaction["who"], "Копилка")
        self.assertEqual(transaction["fingerprint"], fingerprint(row))
        self.assertEqual(row.who, "Дарья Шарыгина")
        client = MagicMock()
        client.delete_expense_row.return_value = True
        with patch("finance_router._get_client", return_value=client):
            finance.delete_transaction("expense", row.id, transaction["fingerprint"], self.db)
        self.assertEqual(client.delete_expense_row.call_args.args[0],
                         original | {"date": "20.10.2026"})
        self.assertEqual(self.db.query(ExpenseLog).count(), 0)

    def test_bank_add_uses_bank_in_both_sheets_and_database_even_if_person_supplied(self):
        client = MagicMock()
        with patch("finance_router._get_client", return_value=client), \
             patch("finance_router._resolve_name") as resolve:
            finance.add_expense(finance.ExpenseRequest(
                project="Театр", amount="500", what="Клининг",
                expense_type=finance.BANK_EXPENSE, who="Дарья Шарыгина", username="actor"), self.db)
        resolve.assert_not_called()
        self.assertEqual(client.add_expense.call_args.args[2], "Копилка")
        self.assertEqual(self.db.query(ExpenseLog).one().who, "Копилка")
        self.assertEqual(finance.get_reimbursements(self.db)["total"], 0)

    def test_named_add_refund_and_delete_refresh_outstanding_debt(self):
        client = MagicMock()
        with patch("finance_router._get_client", return_value=client):
            for kind, amount in [("Личные траты", "500"), ("Возврат", "200")]:
                finance.add_expense(finance.ExpenseRequest(
                    project="Театр", amount=amount, what="Реквизит",
                    expense_type=kind, who="Анна Иванова"), self.db)
                self.assertEqual(client.add_expense.call_args.args[2], "Анна Иванова")
            self.assertEqual(finance.get_reimbursements(self.db)["total"], 300)
            refund = self.db.query(ExpenseLog).filter_by(expense_type="Возврат").one()
            finance.delete_transaction("expense", refund.id, fingerprint(refund), self.db)
        self.assertEqual(finance.get_reimbursements(self.db)["total"], 500)

    def test_person_required_for_new_personal_expenses_and_refunds(self):
        with patch("finance_router._get_client") as client:
            for kind in ("Личные траты", "Возврат"):
                for who in ("", "—", "Копилка"):
                    with self.subTest(kind=kind, who=who), self.assertRaises(HTTPException) as error:
                        finance.add_expense(finance.ExpenseRequest(
                            project="Театр", amount="500", what="Реквизит",
                            expense_type=kind, who=who), self.db)
                    self.assertEqual(error.exception.status_code, 400)
        client.assert_not_called()

    def test_sheet_reconciliation_updates_total_and_does_not_limit_to_recent_transactions(self):
        for _ in range(12):
            self.expense("Анна", 100)
        self.assertEqual(len(finance.get_transactions(db=self.db)["transactions"]), 10)
        self.assertEqual(finance.get_reimbursements(self.db)["total"], 1200)
        values = row_values(self.db.query(ExpenseLog).first())
        reconcile(self.db, ExpenseLog, [values, values | {"expense_type": "Возврат", "amount": 50}])
        self.db.commit()
        self.assertEqual(finance.get_reimbursements(self.db)["total"], 50)
