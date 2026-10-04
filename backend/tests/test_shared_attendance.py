import copy
import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from core.database import Base
    from core.time import as_local
    from bot import _handle_availability_answer, _process_poll_answer, _prepare_campaign
    from modules.attendance.models import DayAnswer
    from modules.attendance.services import record_answers, answered_usernames, export_pending
    from modules.availability.models import AvailabilityCampaign, AvailabilityPoll, AvailabilityPollOption
    from modules.availability.router import create_campaign, CreateCampaignRequest, ping_non_voters, get_non_voters, get_current
    from modules.polling.models import Poll
    from modules.polling.services import PollingService
    from modules.polling.delivery import publish_event
    from modules.polling.router import pin_poll, stop_poll, get_events_poll_summary
    from modules.calendar.models import CalendarEvent
    from modules.theater.models import TheaterShow, TheaterShowAlias
    from modules.theater.routing import event_destination
    from modules.planning.router import read_plan
    from modules.notifications.models import NotificationSetting
    from sheets_client import SheetsClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendPoll

class SharedAttendanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine); self.db = self.Session()
        self.day = date(2026, 10, 7)
        self.a = TheaterShow(name='Калий', normalized_name='калий', telegram_chat_id=-100111)
        self.b = TheaterShow(name='Урод', normalized_name='урод', telegram_chat_id=-100222)
        self.db.add_all([self.a, self.b]); self.db.commit()
        self.sheets = MagicMock()
        self.sheets.get_actor_mapping.return_value = {'shared': 'Анна', 'onlya': 'Борис', 'onlyb': 'Вера'}
        self.source = {'casts': [['Спектакль', 'Роль', 'Актёр'], ['Калий', 'Роль', 'Анна'], ['Калий', 'Другая', 'Борис'], ['Урод', 'Роль', 'Анна'], ['Урод', 'Другая', 'Вера']],
                       'schedule': [['Актёр', '7 окт 2026', '8 окт 2026'], ['', '', ''], ['Анна', '', ''], ['Борис', 'да', ''], ['Вера', 'да', '']]}
        self.sheets.get_planning_data.side_effect = lambda: copy.deepcopy(self.source)
        self.send = AsyncMock(side_effect=lambda **kwargs: NS(poll=NS(id=f'tg-{self.send.call_count}'), message_id=self.send.call_count))
    def tearDown(self):
        self.db.close(); self.engine.dispose()
    def regular(self, title='Калий [Реп]'):
        event = CalendarEvent(title=title, start_time=datetime.combine(self.day, datetime.min.time()))
        self.db.add(event); self.db.commit()
        poll = PollingService(self.db).create_poll(title, 1, calendar_event_id=event.id)
        poll.telegram_poll_id = f'regular-{poll.id}'; self.db.commit()
        return event, poll
    def availability(self):
        poll = AvailabilityPoll(telegram_chat_id=-100222, telegram_poll_id='availability')
        self.db.add(poll); self.db.flush()
        for i, day in enumerate([self.day, date(2026, 10, 8)]):
            self.db.add(AvailabilityPollOption(poll_id=poll.id, selected_date=day, option_index=i))
        self.db.commit(); return poll
    def avote(self, poll, choices):
        _handle_availability_answer(NS(user=NS(id=42, username='shared'), option_ids=choices), poll, self.db, export=False)
    def answer(self):
        return self.db.get(DayAnswer, (42, self.day)).answer
    def vote(self, poll, answer):
        PollingService(self.db).vote(poll.id, 42, answer, 'shared')
    def record(self, source, answer):
        record_answers(self.db, 42, 'shared', source, {self.day: answer}); self.db.commit()

    def test_latest_change_retraction_replay_and_other_date_edit(self):
        _, regular = self.regular(); long = self.availability()
        self.avote(long, [0, 1]); self.vote(regular, 'no')
        self.avote(long, [0, 1]); self.avote(long, [0])
        self.assertEqual(self.answer(), 'no')
        self.avote(long, []); self.assertEqual(self.answer(), 'no')
        self.vote(regular, 'retracted'); self.assertEqual(self.answer(), 'retracted')
        self.assertNotIn('shared', answered_usernames(self.db, self.day))
        self.avote(long, [0]); self.assertEqual(self.answer(), 'yes')

    def test_moved_event_keeps_old_day_and_both_shows_use_same_answer(self):
        event, poll = self.regular()
        event.start_time = datetime(2026, 10, 8); event.title = 'Урод [Реп]'; self.db.commit()
        self.vote(poll, 'yes')
        self.assertIsNone(self.db.get(DayAnswer, (42, date(2026, 10, 8))))
        plan = read_plan(self.sheets, '2026-10', self.db)[1]
        self.assertEqual([s['status'] for s in plan['slots'][0]['shows']], ['ready', 'ready'])
        self.assertNotIn('ready', [s['status'] for s in plan['slots'][1]['shows']])

    def test_user_id_identity_and_duplicate_telegram_update(self):
        _, poll = self.regular()
        update = NS(poll_id=poll.telegram_poll_id, user=NS(id=42, username='shared'), option_ids=[0])
        with patch('core.database.SessionLocal', self.Session), patch('modules.attendance.services.export_pending'):
            _process_poll_answer(update, 100)
            update.user.username = 'renamed'; update.option_ids = [1]; _process_poll_answer(update, 101)
            update.option_ids = [0]; _process_poll_answer(update, 100)
        self.db.expire_all()
        row = self.db.get(DayAnswer, (42, self.day))
        self.assertEqual(row.answer, 'no'); self.assertEqual(row.username, 'renamed')
        self.assertEqual(self.db.query(DayAnswer).count(), 1)

    def test_role_preservation_late_no_and_all_columns_for_day(self):
        self.source['schedule'][1][1] = 'КАЛИЙ'; self.source['schedule'][2][1] = 'Роль'
        self.record('test', 'no')
        source, plan = read_plan(self.sheets, '2026-10', self.db)
        self.assertEqual(source['schedule'][2][1], 'Роль')
        self.assertEqual(plan['slots'][0]['shows'][0]['roles'][0]['actors'][0]['status'], 'no')
        self.assertTrue(plan['warnings'])
        client = SheetsClient.__new__(SheetsClient); client.api = MagicMock(); client.spreadsheet_id = 'test'
        client.get_actor_mapping = MagicMock(return_value={'shared': 'Анна'}); client.find_actor_row = MagicMock(return_value=3)
        client.api.values.return_value.get.return_value.execute.return_value = {'values': [['', '7 окт 2026', '7 окт 2026\n19:00']]}
        client.read_cell = MagicMock(side_effect=['Роль', 'да'])
        self.assertTrue(client.record_poll_answer('shared', datetime(2026, 10, 7), 'no'))
        writes = client.api.values.return_value.update.call_args_list
        self.assertEqual(len(writes), 1); self.assertEqual(writes[0].kwargs['range'], 'График [составы]!C3')

    def test_export_failure_keeps_planning_answer_and_retries_latest(self):
        self.record('first', 'yes')
        with patch('config.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), patch('sheets_client.SheetsClient', return_value=self.sheets):
            self.sheets.record_poll_answer.side_effect = RuntimeError('offline'); export_pending(self.db)
            self.assertEqual(self.db.get(DayAnswer, (42, self.day)).exported_revision, 0)
            self.assertEqual(read_plan(self.sheets, '2026-10', self.db)[1]['slots'][0]['shows'][0]['status'], 'ready')
            self.record('second', 'no'); self.sheets.record_poll_answer.side_effect = None
            self.sheets.record_poll_answer.return_value = True; export_pending(self.db)
        self.assertEqual(self.sheets.record_poll_answer.call_args.args[2], 'no')
        row = self.db.get(DayAnswer, (42, self.day)); self.assertEqual(row.revision, row.exported_revision)

    def test_catalog_and_renamed_shows_keep_roster(self):
        self.a.name = 'Цианистый калий'; self.a.normalized_name = 'цианистый калий'
        self.db.add(TheaterShowAlias(normalized_name='калий', show_id=self.a.id))
        self.db.add(TheaterShow(name='Новый', normalized_name='новый')); self.db.commit()
        plan = read_plan(self.sheets, '2026-10', self.db)[1]
        self.assertEqual(set(plan['shows']), {'Цианистый калий', 'Урод', 'Новый'})
        self.assertTrue(next(s for s in plan['slots'][0]['shows'] if s['show'] == 'Новый')['incomplete'])
        self.assertEqual(event_destination(self.db, self.regular()[0]).id, self.a.id)

    async def test_regular_routes_idempotently_and_original_chat_kept_for_pin_stop(self):
        event, _ = self.regular()
        with patch('bot.bot.send_poll', self.send):
            first = await publish_event(self.db, main.bot, event, 1)
            self.assertEqual(await publish_event(self.db, main.bot, event, 1), first)
            self.assertEqual(self.send.await_count, 1)
            self.a.telegram_chat_id = -100333; self.db.commit()
            await publish_event(self.db, main.bot, event, 1)
        self.assertEqual([c.kwargs['chat_id'] for c in self.send.await_args_list], [-100111, -100333])
        with patch('bot.bot.pin_chat_message', AsyncMock()) as pin, patch('bot.bot.stop_poll', AsyncMock()) as stop:
            await pin_poll(first['poll_id'], self.db); await stop_poll(first['poll_id'], self.db)
            self.assertEqual(pin.call_args.kwargs['chat_id'], -100111); self.assertEqual(stop.call_args.kwargs['chat_id'], -100111)

    async def test_unknown_ambiguous_or_unmapped_show_never_falls_back(self):
        for title in ['Труппа 1', 'Калий и Урод [Реп]', 'Неизвестный [Реп]']:
            event, _ = self.regular(title)
            with self.assertRaises(HTTPException), patch('bot.bot.send_poll', self.send):
                await publish_event(self.db, main.bot, event, 1)
        self.send.assert_not_called()
        self.a.telegram_chat_id = None; self.db.commit()
        with self.assertRaises(HTTPException): event_destination(self.db, self.regular()[0])

    async def test_campaign_deduplicates_chats_and_preserves_history(self):
        req = CreateCampaignRequest(show_names=['Калий', 'Урод'], dates=[self.day])
        with patch('bot.bot.send_poll', self.send), patch('modules.availability.router._ensure_campaign_columns'):
            original = await create_campaign(req, self.db); await create_campaign(req, self.db)
            self.assertEqual(self.send.await_count, 2)
            self.b.telegram_chat_id = self.a.telegram_chat_id; self.db.commit()
            await create_campaign(req, self.db)
        self.assertEqual(self.send.await_count, 3); self.assertEqual(self.db.query(AvailabilityCampaign).count(), 2)
        self.assertEqual(len(get_current(self.db, campaign_id=original['campaign_id'])['campaign']['polls']), 2)

    async def test_failed_chat_does_not_block_other_chat_or_repeat_success(self):
        req = CreateCampaignRequest(show_names=['Калий', 'Урод'], dates=[self.day])
        denied = TelegramForbiddenError(method=SendPoll(chat_id=-100111, question='x', options=['a', 'b']), message='forbidden')
        message = NS(poll=NS(id='sent'), message_id=1)
        send = AsyncMock(side_effect=[denied, message, message])
        with patch('bot.bot.send_poll', send), patch('modules.availability.router._ensure_campaign_columns'):
            result = await create_campaign(req, self.db)
            self.assertEqual(result['status'], 'partial'); self.assertEqual(len(result['errors']), 1)
            self.assertEqual((await create_campaign(req, self.db))['status'], 'sent')
        self.assertEqual(send.await_count, 3); self.assertEqual(send.call_args.kwargs['chat_id'], -100111)

    async def test_uncertain_send_requires_explicit_retry_across_sessions(self):
        req = CreateCampaignRequest(show_names=['Калий'], dates=[self.day])
        send = AsyncMock(side_effect=TimeoutError())
        with patch('bot.bot.send_poll', send), patch('modules.availability.router._ensure_campaign_columns'):
            await create_campaign(req, self.db)
            with self.Session() as another: await create_campaign(req, another)
            self.assertEqual(send.await_count, 1)
            send.side_effect = None; send.return_value = NS(poll=NS(id='retry'), message_id=2)
            self.assertEqual((await create_campaign(req.model_copy(update={'retry_unconfirmed': True}), self.db))['status'], 'sent')
            self.assertEqual(send.await_count, 2)

    async def test_campaign_reminders_tag_own_cast_and_use_regular_answers(self):
        with patch('bot.bot.send_poll', self.send), patch('modules.availability.router._ensure_campaign_columns'):
            await create_campaign(CreateCampaignRequest(show_names=['Калий', 'Урод'], dates=[self.day]), self.db)
        self.vote(self.regular()[1], 'unknown')
        with patch('modules.availability.router.GOOGLE_SHEETS_ID', 'test'), patch('os.path.exists', return_value=True), patch('sheets_client.SheetsClient', return_value=self.sheets), patch('bot.bot.send_message', AsyncMock()) as send:
            self.assertEqual(get_non_voters(self.db)['non_voters'], ['onlya', 'onlyb'])
            await ping_non_voters(self.db)
        messages = {c.kwargs['chat_id']: c.kwargs['text'] for c in send.call_args_list}
        self.assertIn('@onlya', messages[-100111]); self.assertNotIn('@onlyb', messages[-100111])
        self.assertIn('@onlyb', messages[-100222]); self.assertNotIn('@shared', messages[-100222])
        self.assertIn('t.me/c/111/', messages[-100111]); self.assertIn('t.me/c/222/', messages[-100222])

    async def test_auto_polls_and_reminders_respect_shared_answers_and_destination(self):
        self.regular(); self.db.add(NotificationSetting(user_id=1, poll_reminders_enabled=True, reminder_time='00:00', reminder_days_before=3))
        self.record('another-chat', 'yes')
        with patch('main.SessionLocal', self.Session), patch('config.ADMIN_ID', 1), patch('main.local_now', return_value=as_local(datetime(2026, 10, 6, 19))), patch('main.GOOGLE_CALENDAR_JSON', __file__), patch('config.GOOGLE_SHEETS_ID', 'test'), patch('sheets_client.SheetsClient', return_value=self.sheets), patch('bot.bot.send_poll', self.send), patch('bot.bot.send_message', AsyncMock()) as send, patch('bot.bot.pin_chat_message', AsyncMock()) as pin:
            await main._auto_create_polls(); await main._auto_create_polls()
            await main._send_poll_reminders(); await main._send_poll_reminders()
        self.assertEqual(self.send.await_count, 1); self.assertEqual(send.await_count, 1)
        self.assertEqual(send.call_args.kwargs['chat_id'], -100111)
        self.assertIn('@onlya', send.call_args.kwargs['text']); self.assertNotIn('@shared', send.call_args.kwargs['text'])
        self.assertEqual(pin.call_args.kwargs['chat_id'], -100111)

    async def test_summary_excludes_old_date_after_move(self):
        event, poll = self.regular(); self.vote(poll, 'yes')
        event.start_time = datetime(2026, 10, 8); self.db.commit()
        self.assertNotIn(str(event.id), (await get_events_poll_summary(self.db))['summary'])

    def test_bot_campaign_is_scoped_to_requesting_chat(self):
        with patch('core.database.SessionLocal', self.Session):
            self.assertEqual(_prepare_campaign(2026, 10, -100111).show_names, ['Калий'])
            self.assertEqual(_prepare_campaign(2026, 10, -100999).show_names, [])

    def test_legacy_migration_freezes_chat_and_day_once(self):
        event, poll = self.regular()
        poll.telegram_chat_id = None; poll.selected_date = None; poll.telegram_message_id = 10; self.db.commit()
        with patch('main.engine', self.engine), patch('config.GROUP_CHAT_ID', -100999): main.run_migrations()
        self.db.expire_all()
        self.assertEqual(poll.telegram_chat_id, -100999); self.assertEqual(poll.selected_date, self.day)
        event.start_time = datetime(2026, 10, 8); self.db.commit()
        with patch('main.engine', self.engine), patch('config.GROUP_CHAT_ID', -100888): main.run_migrations()
        self.db.expire_all()
        self.assertEqual(poll.telegram_chat_id, -100999); self.assertEqual(poll.selected_date, self.day)

    async def test_automatic_job_does_not_reopen_poll_closed_by_admin(self):
        event, _ = self.regular()
        with patch('bot.bot.send_poll', self.send):
            result = await publish_event(self.db, main.bot, event, 1)
            poll = self.db.get(Poll, result['poll_id']); poll.is_active = False; self.db.commit()
            again = await publish_event(self.db, main.bot, event, 1, automatic=True)
        self.assertEqual(again['status'], 'stopped'); self.assertEqual(self.send.await_count, 1)

    async def test_new_date_gets_new_publication_while_same_date_new_show_keeps_answer(self):
        event, _ = self.regular()
        with patch('bot.bot.send_poll', self.send):
            first = await publish_event(self.db, main.bot, event, 1)
            self.vote(self.db.get(Poll, first['poll_id']), 'yes')
            event.title = 'Урод [Реп]'; self.db.commit()
            await publish_event(self.db, main.bot, event, 1)
            self.assertEqual(self.answer(), 'yes')
            event.start_time = datetime(2026, 10, 8); self.db.commit()
            moved = await publish_event(self.db, main.bot, event, 1)
            self.assertIsNone(self.db.get(DayAnswer, (42, date(2026, 10, 8))))
            self.assertEqual(self.db.get(Poll, moved['poll_id']).selected_date, date(2026, 10, 8))
        self.assertEqual([c.kwargs['chat_id'] for c in self.send.await_args_list], [-100111, -100222, -100222])

    async def test_archive_and_delete_publication_preserve_shared_answer(self):
        event, poll = self.regular(); self.vote(poll, 'yes')
        event.end_time = datetime(2026, 10, 7, 20); self.db.commit()
        with patch('main.SessionLocal', self.Session), patch('main.local_now', return_value=as_local(datetime(2026, 10, 10))):
            await main._cleanup_old_polls()
        self.db.expire_all()
        self.assertFalse(poll.is_active); self.assertEqual(self.answer(), 'yes')
        self.db.delete(poll); self.db.commit()
        self.assertEqual(self.answer(), 'yes')
