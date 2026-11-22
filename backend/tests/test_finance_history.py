import unittest

from test_finance_reimbursements import finance, ExpenseLog, IncomeLog, fingerprint, reconcile, row_values
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FinanceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        for model in (ExpenseLog, IncomeLog):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        for index in range(27):
            model = ExpenseLog if index % 2 else IncomeLog
            self.db.add(model(date='20.10.2026' if index % 3 else '2026-10-19',
                              amount=100, what=f'Операция {index}'))
        self.db.add(ExpenseLog(date='invalid', amount=100, what='Без даты'))
        self.db.commit()

    def test_pages_reach_entire_mixed_ledger_without_duplicates_or_gaps(self):
        cursor, rows, sizes = None, [], []
        while True:
            page = finance.get_transactions(db=self.db, cursor=cursor)
            rows.extend(page['transactions'])
            sizes.append(len(page['transactions']))
            cursor = page['next_cursor']
            if cursor is None:
                break
        self.assertEqual(sizes, [10, 10, 8])
        self.assertEqual(len({(r['type'], r['id']) for r in rows}), 28)
        self.assertEqual(rows[-1]['what'], 'Без даты')
        self.assertEqual(rows[-1]['date'], '')
        self.assertEqual([r['date'] for r in rows[:10]], ['20.10.2026'] * 10)
        self.assertFalse(any('_iso' in r for r in rows))

    def test_insert_edit_or_delete_requires_refresh_instead_of_skipping_rows(self):
        for change in ('insert', 'edit', 'delete'):
            with self.subTest(change=change):
                page = finance.get_transactions(db=self.db)
                if change == 'insert':
                    self.db.add(IncomeLog(date='2026-10-21', amount=100))
                elif change == 'edit':
                    self.db.query(ExpenseLog).first().amount += 1
                else:
                    self.db.delete(self.db.query(ExpenseLog).first())
                self.db.commit()
                with self.assertRaises(HTTPException) as error:
                    finance.get_transactions(db=self.db, cursor=page['next_cursor'])
                self.assertEqual(error.exception.status_code, 409)

    def test_unchanged_sheet_sync_preserves_cursor_and_deletion_fingerprints(self):
        first = finance.get_transactions(db=self.db)
        reconcile(self.db, ExpenseLog, [row_values(r) for r in self.db.query(ExpenseLog)])
        self.db.commit()
        second = finance.get_transactions(db=self.db, cursor=first['next_cursor'])
        self.assertEqual(len(second['transactions']), 10)
        row = next(r for r in second['transactions'] if r['type'] == 'expense')
        self.assertEqual(row['fingerprint'], fingerprint(self.db.get(ExpenseLog, row['id'])))

    def test_invalid_page_parameters_are_rejected(self):
        for params in ({'limit': 0}, {'limit': -1}, {'limit': 101},
                       {'cursor': 'garbage'}, {'cursor': 'e30='}, {'cursor': 'a' * 600}):
            with self.subTest(params=params), self.assertRaises(HTTPException) as error:
                finance.get_transactions(db=self.db, **params)
            self.assertEqual(error.exception.status_code, 422)

    def test_empty_ledger_has_no_next_page(self):
        self.db.query(ExpenseLog).delete()
        self.db.query(IncomeLog).delete()
        self.db.commit()
        self.assertEqual(finance.get_transactions(db=self.db), dict(transactions=[], next_cursor=None))
