import copy
import os
import re
import unittest
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from bot import _process_poll_answer
    from core.database import Base
    from modules.attendance.models import DayAnswer, VoterRegistration
    from modules.attendance.registration import sync_voter_registrations
    from modules.attendance.services import export_pending
    from modules.availability.models import AvailabilityPoll, AvailabilityPollOption
    from modules.calendar.models import CalendarEvent
    from modules.polling.services import PollingService
    from modules.theater.models import TheaterShow
    from sheets_client import SheetsClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class SheetState:
    """Stateful Sheets fake: writes can succeed while their HTTP response is lost."""
    def __init__(self):
        self.data = {
            'Труппа': [['Имя'] + [''] * 8 + ['Telegram'], ['Анна'] + [''] * 8 + ['anna']],
            'График [составы]': [['Актёр', '7 окт 2026'], ['', 'УРОД'], ['Анна', 'Роль']],
        }
        self.fail_after_write = False
        self.client = SheetsClient.__new__(SheetsClient)
        self.client.spreadsheet_id = 'offline'
        self.client.api = MagicMock()
        values = self.client.api.values.return_value
        values.get.side_effect = lambda **kw: NS(execute=lambda: self.read(kw['range']))
        values.batchUpdate.side_effect = lambda **kw: NS(execute=lambda: self.write(kw['body']['data']))
        self.client._ensure_grid = MagicMock()

    def read(self, address):
        name = address.split('!')[0].strip("'")
        return {'values': copy.deepcopy(self.data[name])}

    def write(self, changes):
        for change in changes:
            name, address = change['range'].split('!')
            col, row = re.fullmatch(r'([A-Z]+)(\d+)', address).groups()
            column = 0
            for letter in col:
                column = column * 26 + ord(letter) - 64
            rows = self.data[name.strip("'")]
            while len(rows) < int(row):
                rows.append([])
            target = rows[int(row) - 1]
            while len(target) < column:
                target.append('')
            target[column - 1] = change['values'][0][0]
        if self.fail_after_write:
            self.fail_after_write = False
            raise TimeoutError('response lost after applying write')
        return {}


class SheetRegistrationTests(unittest.TestCase):
    def test_legacy_username_keeps_name_roles_and_existing_columns(self):
        state = SheetState()
        state.data['Труппа'][0].append('Телефон')
        state.data['Труппа'][1].append('existing value')
        self.assertEqual(state.client.ensure_poll_participant(42, 'ANNA', 'Ник из Telegram'), 'Анна')
        self.assertEqual(state.data['Труппа'][0][-1], 'Telegram ID')
        self.assertEqual(state.data['Труппа'][1][10:], ['existing value', '42'])
        self.assertEqual(len(state.data['Труппа']), 2)
        self.assertEqual(state.data['График [составы]'][2], ['Анна', 'Роль'])

    def test_timeout_then_retry_does_not_duplicate_rows(self):
        state = SheetState()
        state.fail_after_write = True
        with self.assertRaises(TimeoutError):
            state.client.ensure_poll_participant(43, 'boris', 'Борис')
        self.assertEqual(state.client.ensure_poll_participant(43, 'boris', 'Борис'), 'Борис')
        self.assertEqual(len(state.data['Труппа']), 3)
        self.assertEqual(len(state.data['График [составы]']), 4)

    def test_no_username_same_name_and_renames_use_id(self):
        state = SheetState()
        name = state.client.ensure_poll_participant(43, None, 'Анна')
        self.assertEqual(name, 'Анна [TG 43]')
        self.assertEqual(state.client.ensure_poll_participant(43, 'newname', 'Другое имя'), name)
        self.assertEqual(state.client.ensure_poll_participant(43, None, 'Другое имя'), name)
        self.assertEqual(len(state.data['Труппа']), 3)
        self.assertEqual(state.data['Труппа'][2][9], '')

    def test_reused_username_cannot_take_another_id(self):
        state = SheetState()
        state.client.ensure_poll_participant(42, 'anna', 'Анна')
        before = copy.deepcopy(state.data)
        with self.assertRaises(ValueError):
            state.client.ensure_poll_participant(43, 'anna', 'Анна')
        self.assertEqual(state.data, before)

    def test_partial_existing_troupe_registration_repairs_missing_schedule_row(self):
        state = SheetState()
        state.client.ensure_poll_participant(43, 'boris', 'Борис')
        state.data['График [составы]'].pop()
        state.client.ensure_poll_participant(43, 'boris', 'Борис')
        self.assertEqual(len(state.data['Труппа']), 3)
        self.assertEqual(state.data['График [составы]'][-1], ['Борис'])

    def test_formula_like_display_name_written_as_raw(self):
        state = SheetState()
        state.client.ensure_poll_participant(43, None, '=IMPORTXML("url")')
        body = state.client.api.values.return_value.batchUpdate.call_args.kwargs['body']
        self.assertEqual(body['valueInputOption'], 'RAW')

    def test_duplicate_legacy_username_is_not_guessed(self):
        state = SheetState()
        state.data['Труппа'].append(['Другая Анна'] + [''] * 8 + ['anna'])
        with self.assertRaises(ValueError):
            state.client.ensure_poll_participant(42, 'anna', 'Анна')
        state.client.api.values.return_value.batchUpdate.assert_not_called()


class VoterRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.db.add(TheaterShow(name='Новый', normalized_name='новый', telegram_chat_id=-100111))
        event = CalendarEvent(title='Новый [Реп]', start_time=datetime(2026, 10, 7, 19))
        self.db.add(event)
        self.db.commit()
        self.poll = PollingService(self.db).create_poll('Новый', 1, calendar_event_id=event.id)
        self.poll.telegram_poll_id = 'regular'
        self.poll.telegram_chat_id = -100111
        self.db.commit()
        self.update = NS(poll_id='regular', user=NS(id=42, first_name='Анна', last_name='Иванова',
                                                   username=None, is_bot=False), option_ids=[0])
        self.patches = [
            patch('core.database.SessionLocal', self.Session),
            patch('config.GOOGLE_SHEETS_ID', 'offline'),
            patch('os.path.exists', return_value=True),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = MagicMock()
        self.client.get_actor_mapping.return_value = {}
        self.client.ensure_poll_participant.return_value = 'Анна Иванова'
        self.client.record_poll_answer.return_value = True
        p = patch('sheets_client.SheetsClient', return_value=self.client)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def voter(self):
        self.db.expire_all()
        return self.db.get(VoterRegistration, 42)

    def answer(self):
        self.db.expire_all()
        return self.db.get(DayAnswer, (42, date(2026, 10, 7)))

    async def verify(self, status='member'):
        bot = NS(get_chat_member=AsyncMock(return_value=NS(status=status, is_member=False)))
        await sync_voter_registrations(bot)
        return bot

    async def test_regular_vote_without_username_verified_then_exported(self):
        _process_poll_answer(self.update, 1)
        self.assertEqual(self.answer().answer, 'yes')
        self.assertEqual(self.voter().membership_status, 'pending')
        self.client.ensure_poll_participant.assert_not_called()
        await self.verify()
        export_pending(self.db)
        self.client.ensure_poll_participant.assert_called_once_with(42, None, 'Анна Иванова')
        self.assertEqual(self.answer().actor_name, 'Анна Иванова')
        self.assertEqual(self.answer().exported_revision, 1)
        self.assertIsNone(self.client.record_poll_answer.call_args.args[0])
        _process_poll_answer(self.update, 1)
        self.assertEqual(self.voter().revision, 1)

    async def test_monthly_vote_registers_and_failed_sheet_write_retries_latest_answer(self):
        monthly = AvailabilityPoll(telegram_poll_id='monthly', telegram_chat_id=-100111)
        self.db.add(monthly)
        self.db.flush()
        self.db.add(AvailabilityPollOption(poll_id=monthly.id, selected_date=date(2026, 10, 7), option_index=0))
        self.db.commit()
        self.update.poll_id = 'monthly'
        _process_poll_answer(self.update, 1)
        await self.verify()
        self.client.ensure_poll_participant.side_effect = TimeoutError('offline')
        export_pending(self.db)
        self.assertEqual(self.answer().exported_revision, 0)
        self.update.option_ids = [1]  # none of the dates
        _process_poll_answer(self.update, 2)
        self.client.ensure_poll_participant.side_effect = None
        export_pending(self.db)
        self.assertEqual(self.answer().answer, 'no')
        self.assertEqual(self.client.record_poll_answer.call_args.args[2], 'no')
        self.assertEqual(self.answer().exported_revision, self.answer().revision)

    async def test_forwarded_vote_from_nonmember_is_not_enrolled(self):
        _process_poll_answer(self.update, 1)
        await self.verify('left')
        export_pending(self.db)
        self.client.ensure_poll_participant.assert_not_called()
        self.assertEqual(self.answer().answer, 'yes')

    async def test_membership_timeout_keeps_vote_and_pending_registration(self):
        _process_poll_answer(self.update, 1)
        await sync_voter_registrations(NS(get_chat_member=AsyncMock(side_effect=TimeoutError())))
        self.assertEqual(self.voter().membership_status, 'pending')
        self.assertEqual(self.answer().answer, 'yes')
        await self.verify()
        export_pending(self.db)
        self.assertEqual(self.answer().exported_revision, 1)

    async def test_unknown_invalid_and_retracted_votes_do_not_enroll(self):
        self.update.poll_id = 'unknown'
        _process_poll_answer(self.update, 1)
        self.update.poll_id = 'regular'
        self.update.option_ids = [999]
        _process_poll_answer(self.update, 2)
        self.update.option_ids = []
        _process_poll_answer(self.update, 3)
        self.assertIsNone(self.voter())

    async def test_username_change_does_not_duplicate_voter_or_change_answer_precedence(self):
        _process_poll_answer(self.update, 1)
        await self.verify()
        export_pending(self.db)
        self.update.user.username = 'new_name'
        _process_poll_answer(self.update, 2)
        await self.verify()
        export_pending(self.db)
        self.assertEqual(self.db.query(VoterRegistration).count(), 1)
        self.assertEqual(self.answer().revision, 1)
        self.assertEqual(self.voter().username, 'new_name')

    async def test_disconnected_group_not_registered(self):
        _process_poll_answer(self.update, 1)
        show = self.db.query(TheaterShow).first()
        show.telegram_chat_id = None
        self.db.commit()
        await self.verify()
        export_pending(self.db)
        self.client.ensure_poll_participant.assert_not_called()

    async def test_later_export_failure_keeps_completed_progress(self):
        _process_poll_answer(self.update, 1)
        await self.verify()
        self.db.add(DayAnswer(user_id=43, day=date(2026, 10, 7), username='boris',
                             answer='yes', source='test', revision=1, exported_revision=0))
        self.db.commit()
        self.client.get_actor_mapping.return_value = {'boris': 'Борис'}
        self.client.record_poll_answer.side_effect = [True, TimeoutError('quota')]
        export_pending(self.db)
        self.assertEqual(self.answer().exported_revision, 1)
        self.assertEqual(self.db.get(DayAnswer, (43, date(2026, 10, 7))).exported_revision, 0)
        self.client.record_poll_answer.side_effect = None
        export_pending(self.db)
        self.assertEqual(self.db.get(DayAnswer, (43, date(2026, 10, 7))).exported_revision, 1)

    async def test_next_vote_refreshes_manually_renamed_actor_without_changing_telegram_name(self):
        _process_poll_answer(self.update, 1)
        await self.verify()
        export_pending(self.db)
        self.client.ensure_poll_participant.return_value = 'Анна Петрова'
        self.update.option_ids = [1]
        _process_poll_answer(self.update, 2)
        self.assertEqual(self.answer().actor_name, 'Анна Петрова')
        self.assertEqual(self.client.record_poll_answer.call_args.kwargs['actor_name'], 'Анна Петрова')


if __name__ == '__main__':
    unittest.main()
