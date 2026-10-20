import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from core import access
    from core.database import Base
    from modules.attendance.models import ChatParticipant, VoterRegistration, DayAnswer
    from modules.attendance.registration import remember_voter, membership_event, sync_voter_registrations, backfill_participants
    from modules.attendance.roster import members, missing_members, attendance_totals, mention_messages
    from modules.attendance.services import record_answers, export_pending
    from modules.theater.models import TheaterShow
    from modules.planning.router import read_plan
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
from fastapi.testclient import TestClient


class GroupParticipantsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.db.add_all([TheaterShow(name='Первый', normalized_name='первый', telegram_chat_id=-1001),
                         TheaterShow(name='Второй', normalized_name='второй', telegram_chat_id=-1002)])
        self.db.commit()
        self.user = NS(id=42, username=None, first_name='Анна <&>', last_name='', is_bot=False)
        self.day = date(2026, 10, 7)
        access._access_cache.clear()
        for target, value in [('core.database.SessionLocal', self.Session), ('modules.admin.services.SessionLocal', self.Session),
                              ('core.access.GROUP_CHAT_ID', 0),
                              ('core.access.is_super_admin', AsyncMock(return_value=False))]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def join(self, chat, user=None):
        membership_event(chat, user or self.user, NS(status='member', is_member=True))
        self.db.expire_all()

    async def test_multichat_membership_and_leave_preserve_other_chat(self):
        self.join(-1001)
        self.join(-1002)
        self.assertEqual(self.db.query(VoterRegistration).count(), 1)
        self.assertEqual(self.db.query(ChatParticipant).count(), 2)
        membership_event(-1002, self.user, NS(status='left'))
        self.db.expire_all()
        self.assertEqual(len(members(self.db, -1001)), 1)
        self.assertEqual(members(self.db, -1002), [])
        self.assertEqual(self.db.get(VoterRegistration, 42).membership_status, 'member')
        self.assertEqual(self.db.get(VoterRegistration, 42).telegram_chat_id, -1001)

    async def test_stale_verification_cannot_overwrite_leave_event(self):
        from modules.attendance.registration import _mark
        self.join(-1001)
        revision = self.db.get(ChatParticipant, (-1001, 42)).revision
        membership_event(-1001, self.user, NS(status='left'))
        _mark(42, -1001, revision, 'member')
        self.db.expire_all()
        self.assertEqual(members(self.db, -1001), [])

    async def test_group_access_without_username_or_sheets_then_revoked(self):
        user = access.TelegramUser(42, '', 'Анна')
        statuses = {-1001: 'member', -1002: 'left'}
        async def check(chat, uid):
            return NS(status=statuses[chat], is_member=False)
        with patch.object(main.bot, 'get_chat_member', side_effect=check):
            self.assertEqual(await access._permissions(user), (True, False, False))
            self.assertFalse(access._access_cache)  # no stale allow after departure
            statuses[-1001] = 'left'
            self.assertEqual(await access._permissions(user), (False, False, False))

    async def test_restricted_member_allowed_but_timeout_not_cached(self):
        user = access.TelegramUser(42)
        with patch.object(main.bot, 'get_chat_member', AsyncMock(return_value=NS(status='restricted', is_member=True))):
            self.assertTrue((await access._permissions(user))[0])
        with patch.object(main.bot, 'get_chat_member', AsyncMock(side_effect=TimeoutError())):
            with self.assertRaises(HTTPException) as error:
                await access._permissions(user)
            self.assertEqual(error.exception.status_code, 503)
        self.assertFalse(access._access_cache)

    async def test_disconnecting_group_revokes_access_on_next_request(self):
        with patch.object(main.bot, 'get_chat_member', AsyncMock(return_value=NS(status='member'))):
            self.assertTrue((await access._permissions(access.TelegramUser(42)))[0])
            for show in self.db.query(TheaterShow):
                show.telegram_chat_id = None
            self.db.commit()
            self.assertFalse((await access._permissions(access.TelegramUser(42)))[0])

    async def test_new_sheet_row_cannot_grant_permanent_access_or_finance(self):
        self.user.username = 'new_actor'
        self.join(-1001)
        sheets = MagicMock()
        sheets.get_actor_mapping.return_value = {}
        sheets.ensure_poll_participant.return_value = 'Анна'
        with patch('config.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), \
             patch('sheets_client.SheetsClient', return_value=sheets):
            export_pending(self.db)
            sheets.get_actor_mapping.return_value = {'new_actor': 'Анна'}
            self.assertFalse(access._known_actor('new_actor'))
            self.assertFalse(self.db.get(VoterRegistration, 42).legacy_access)

    async def test_conflicting_or_reused_username_cannot_grant_legacy_access(self):
        self.db.add(VoterRegistration(user_id=42, username='actor', display_name='Анна',
            telegram_chat_id=-1001, legacy_access=True, revision=2, exported_revision=1))
        self.db.commit()
        self.assertFalse(access._known_actor('actor', 42))  # unverified new binding
        self.db.get(VoterRegistration, 42).exported_revision = 2
        self.db.commit()
        self.assertFalse(access._known_actor('actor', 99))  # username now used by another ID

    async def test_counts_without_roles_and_common_answers_across_chats(self):
        self.join(-1001); self.join(-1002)
        other = NS(id=43, username='boris', first_name='Борис', last_name='', is_bot=False)
        self.join(-1001, other)
        record_answers(self.db, 42, None, 'other-chat', {self.day: 'yes'})
        self.db.commit()
        counts = attendance_totals(self.db, -1001, self.day)
        self.assertEqual((counts['total'], counts['yes'], counts['unanswered']), (2, 1, 1))
        self.assertEqual([p['user_id'] for p in missing_members(self.db, -1001, [self.day])], [43])
        self.assertEqual(missing_members(self.db, -1002, [self.day]), [])
        client = MagicMock()
        client.get_actor_mapping.return_value = {}
        client.get_planning_data.return_value = {
            'casts': [['Спектакль', 'Роль', 'Актёр']], 'schedule': [['Актёр', '7 окт 2026'], ['', '']]}
        plan = read_plan(client, '2026-10', self.db)[1]
        cell = next(c for c in plan['slots'][0]['shows'] if c['show'] == 'Первый')
        self.assertTrue(cell['incomplete'])
        self.assertEqual(cell['attendance']['yes'], 1)
        record_answers(self.db, 42, None, 'other-chat', {self.day: 'retracted'})
        self.db.commit()
        self.assertEqual(len(missing_members(self.db, -1001, [self.day])), 2)

    async def test_mentions_escape_names_and_do_not_require_username(self):
        self.join(-1001)
        text = list(mention_messages('Первый <&>', members(self.db, -1001)))[0]
        self.assertIn('tg://user?id=42', text)
        self.assertIn('Анна &lt;&amp;&gt;', text)
        self.assertNotIn('Анна <&>', text)

    async def test_failed_refresh_stops_reminder_instead_of_using_stale_members(self):
        self.join(-1001)
        with patch.object(main.bot, 'get_chat_member', AsyncMock(side_effect=TimeoutError())):
            with self.assertRaises(HTTPException):
                await sync_voter_registrations(main.bot, chat_ids=[-1001], force=True, strict=True)

    async def test_periodic_refresh_detects_missed_departure(self):
        self.join(-1001)
        self.db.get(ChatParticipant, (-1001, 42)).checked_at = datetime(2000, 1, 1)
        self.db.commit()
        with patch.object(main.bot, 'get_chat_member', AsyncMock(return_value=NS(status='left'))):
            await sync_voter_registrations(main.bot)
        self.db.expire_all()
        self.assertEqual(members(self.db, -1001), [])

    async def test_polling_requests_membership_updates(self):
        self.assertIn('chat_member', main.dp.resolve_used_update_types())

    async def test_backfill_existing_registration_idempotent_and_no_answers_invented(self):
        self.db.add(VoterRegistration(user_id=42, display_name='Анна', telegram_chat_id=-1001))
        self.db.commit()
        backfill_participants(self.db)
        backfill_participants(self.db)
        self.assertEqual(self.db.query(ChatParticipant).count(), 1)
        self.assertEqual(self.db.query(DayAnswer).count(), 0)

    async def test_members_cannot_read_finance_or_change_admin_settings(self):
        with patch('core.access.verify_init_data', return_value=access.TelegramUser(42)), \
             patch.object(main.bot, 'get_chat_member', AsyncMock(return_value=NS(status='member'))), \
             patch('main.RECOVERY_MODE', False):
            client = TestClient(main.app)
            self.addCleanup(client.close)
            auth = client.get('/api/auth/check')
            self.assertEqual(auth.status_code, 200)
            self.assertFalse(auth.json()['can_finance'])
            self.assertFalse(auth.json()['is_admin'])
            self.assertEqual(client.get('/api/finance/balance').status_code, 403)
            self.assertEqual(client.get('/api/finance/reimbursements').status_code, 403)
            self.assertEqual(client.get('/api/admin/theater').status_code, 403)
            self.assertEqual(client.post('/api/calendar/events').status_code, 403)


if __name__ == '__main__':
    unittest.main()
