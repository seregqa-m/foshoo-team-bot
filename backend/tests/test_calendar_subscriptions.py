import copy
import os
import unittest
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://'}, clear=True), patch('dotenv.load_dotenv'):
    import main
    from core.database import Base, get_db
    from core.time import local_now
    from modules.calendar import subscriptions as sub
    from modules.calendar.ical import render_calendar
    from modules.calendar.models import CalendarEvent, CalendarSubscription
    from modules.theater.models import TheaterShow, TheaterShowAlias
    from modules.assistant.services import AssistantService, _decode_action_token
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


class CalendarSubscriptionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.shows = [TheaterShow(name='Урод', normalized_name='урод'), TheaterShow(name='Цианистый Калий', normalized_name='цианистый калий')]
        self.db.add_all(self.shows)
        self.db.flush()
        self.db.add(TheaterShowAlias(normalized_name='калий', show_id=self.shows[1].id))
        self.db.commit()
        self.source = {'troupe': [['Имя'], ['Анна'], ['Борис'], ['Вера']], 'casts': [
            ['Спектакль', 'Роль', 'Актёр'], ['Урод', 'Роль', 'Анна'], ['Калий', 'Роль', 'Анна'],
            ['Калий', 'Роль', 'Борис'], ['Урод', 'Роль', 'Вера'], ['Калий', 'Роль', 'Вера']]}
        for mock in (patch.object(sub, 'read_roster', side_effect=lambda: copy.deepcopy(self.source)),
                     patch.object(sub, 'public_base_url', return_value='https://theater.example')):
            mock.start()
            self.addCleanup(mock.stop)

    def event(self, title, **kwargs):
        now = local_now()
        row = CalendarEvent(title=title, start_time=now + timedelta(days=1), end_time=now + timedelta(days=1, hours=2), **kwargs)
        self.db.add(row)
        self.db.commit()
        return row

    def rebuild(self):
        return sub.rebuild_links(self.db, sub.prepare_links(self.db)['fingerprint'])

    def test_only_real_combinations_no_power_set_or_participant_names(self):
        plan = sub.prepare_links(self.db)
        self.assertEqual({tuple(g['show_ids']) for g in plan['groups']}, {(1, 2), (2,)})
        self.assertEqual(len(plan['groups']), 2)  # Two actors share one combination.
        self.assertNotIn('Анна', str(plan))
        self.assertNotIn('Борис', str(plan))
        self.assertEqual(self.db.query(CalendarSubscription).count(), 0)
        self.source['casts'].append(['Цианистый Калий', 'Другая роль', 'Анна'])
        self.assertEqual(sub.prepare_links(self.db), plan)  # Alias/duplicate role does not create new combinations.

    def test_rebuild_preserves_urls_and_old_combinations_and_adds_only_new_ones(self):
        first = self.rebuild()
        self.assertEqual(first, self.rebuild())
        self.source['casts'] = self.source['casts'][:1] + [['Урод', 'Роль', 'Анна']]
        result = self.rebuild()
        self.assertEqual(result['count'], 1)
        self.assertEqual(self.db.query(CalendarSubscription).count(), 3)
        old_tokens = [link['url'] for link in first['calendar_links']]
        self.assertTrue(all(self.db.query(CalendarSubscription).filter_by(token=url.split('/')[-1][:-4]).first() for url in old_tokens))

    def test_changes_after_preview_rejected_without_publishing(self):
        fingerprint = sub.prepare_links(self.db)['fingerprint']
        self.source['casts'].append(['Урод', 'Роль', 'Глеб'])
        with self.assertRaises(HTTPException) as error: sub.rebuild_links(self.db, fingerprint)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(CalendarSubscription).count(), 0)

    def test_explicit_selection_without_sheets_can_create_a_new_combination(self):
        with patch.object(sub, 'read_roster', side_effect=AssertionError('explicit choice must not read Sheets')):
            plan = sub.prepare_links(self.db, ['Урод', 'урод'])
            self.assertEqual(plan['show_names'], ['Урод'])
            self.assertEqual(plan['groups'][0]['show_ids'], [1])
            result = sub.rebuild_links(self.db, plan['fingerprint'], show_names=plan['show_names'])
            self.assertEqual(result['count'], 1)
            self.assertEqual(result['calendar_links'][0]['show_ids'], [1])
        self.assertEqual(self.db.query(CalendarSubscription).count(), 1)

    def test_explicit_aliases_reuse_batch_links_and_unknown_names_fail(self):
        existing = self.rebuild()
        plan = sub.prepare_links(self.db, ['Калий', 'Урод'])
        result = sub.rebuild_links(self.db, plan['fingerprint'], show_names=plan['show_names'])
        same = next(row for row in existing['calendar_links'] if row['show_ids'] == [1, 2])
        self.assertEqual(result['calendar_links'], [same])
        for invalid in ([], [''], ['Урод', 'Опечатка'], 'Урод'):
            with self.subTest(invalid=invalid), self.assertRaises(HTTPException):
                sub.prepare_links(self.db, invalid)

    async def test_assistant_explicit_choice_is_frozen_and_executed(self):
        service = AssistantService(self.db)
        service.llm = AsyncMock()
        service.llm.chat.return_value = SimpleNamespace(input_tokens=0, output_tokens=0, text='', tool_calls=[
            SimpleNamespace(name='rebuild_calendar_links', arguments={'show_names': ['Калий']}, id='call1')])
        with patch('modules.assistant.services._build_system_prompt', return_value='test'), \
                patch.object(sub, 'read_roster', side_effect=AssertionError('no Sheets')):
            prepared = await service.chat(user_id=42, message='Ссылка только на Калий', is_admin=True)
            payload = _decode_action_token(prepared.pending_action.action_token)
            self.assertEqual(payload['args']['show_names'], ['Цианистый Калий'])
            response = await service.execute_pending(user_id=42, action_token=prepared.pending_action.action_token, is_admin=True)
        self.assertEqual(response['result']['calendar_links'][0]['show_ids'], [2])

    def test_invalid_or_empty_source_never_creates_partial_links(self):
        for mutation in ('unknown', 'duplicate_name', 'empty', 'incomplete'):
            source = copy.deepcopy(self.source)
            if mutation == 'unknown': source['casts'].append(['Неизвестный', 'Роль', 'Анна'])
            if mutation == 'duplicate_name': source['troupe'].append(['Анна'])
            if mutation == 'empty': source['casts'] = source['casts'][:1]
            if mutation == 'incomplete': source['casts'].append(['Урод', 'Роль'])
            with self.subTest(mutation=mutation), self.assertRaises(HTTPException): sub.combination_plan(self.db, source)
        self.assertEqual(self.db.query(CalendarSubscription).count(), 0)

    def test_immutable_selection_live_events_and_private_notes(self):
        self.rebuild()
        row = self.db.query(CalendarSubscription).filter_by(show_ids=[2]).one()
        self.event('Урод [Реп]')
        event = self.event('Калий [Реп]', description='PRIVATE ROLE DATA')
        self.event('Калий [Спект]')
        self.event('Уборка')
        self.event('Урод и Калий [Реп]')
        self.event('Калий [Реп]', is_cancelled=True)
        body = sub.build_feed(self.db, row)
        self.assertEqual(body.count('BEGIN:VEVENT'), 3)
        self.assertIn('STATUS:CANCELLED', body)
        self.assertNotIn('PRIVATE ROLE DATA', body)
        self.assertNotIn('Урод', body)
        event.start_time += timedelta(days=1)
        event.end_time += timedelta(days=1)
        self.db.commit()
        self.assertIn(f'UID:calendar-event-{event.id}@foshoo', sub.build_feed(self.db, row))
        self.source['casts'] = self.source['casts'][:1]  # Feed never depends on live Sheets/participant access.
        with patch.object(sub, 'read_roster', side_effect=AssertionError('feed must not read Sheets')):
            self.assertEqual(sub.build_feed(self.db, row).count('BEGIN:VEVENT'), 3)

    def test_rfc_folding_escaping_all_day_and_utc(self):
        event = self.event('Я' * 100 + ',;\\\nEND:VEVENT', is_all_day=True, location='A, B; C')
        body = render_calendar([event], 'Набор,;\nНазвание')
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split('\r\n')))
        self.assertIn('DTSTART;VALUE=DATE:', body)
        self.assertIn('LOCATION:A\\, B\\; C', body)
        unfolded = body.replace('\r\n ', '')
        self.assertIn('\\nEND:VEVENT', unfolded)
        self.assertEqual(unfolded.count('\r\nEND:VEVENT\r\n'), 1)
        event.is_all_day = False
        self.assertIn(event.start_time.astimezone(timezone.utc).strftime('DTSTART:%Y%m%dT%H%M%SZ'), render_calendar([event]))

    def test_shared_feed_works_without_any_telegram_session_and_revocation_survives_rebuild(self):
        link = self.rebuild()['calendar_links'][0]
        path = link['url'].replace('https://theater.example', '')
        def get_test_db(): yield self.db
        main.app.dependency_overrides[get_db] = get_test_db
        self.addCleanup(main.app.dependency_overrides.clear)
        client = TestClient(main.app)
        self.addCleanup(client.close)
        with patch('main.RECOVERY_MODE', False), patch('core.access._permissions', AsyncMock(side_effect=AssertionError('no Telegram check'))):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('text/calendar', response.headers['content-type'])
            self.assertEqual(client.head(path).headers['content-length'], str(len(response.content)))
            self.assertEqual(client.get('/api/calendar/events').status_code, 401)
            self.assertEqual(client.get('/api/calendar/feeds/bad.ics').status_code, 404)
            with patch('main.RECOVERY_MODE', True): self.assertEqual(client.get(path).status_code, 503)
            row = self.db.query(CalendarSubscription).filter_by(token=path.split('/')[-1][:-4]).one()
            sub.revoke_link(self.db, row.id)
            self.rebuild()
            self.assertEqual(client.get(path).status_code, 404)

    async def test_assistant_prepares_concrete_sets_and_returns_links_with_replay_protection(self):
        service = AssistantService(self.db)
        service.llm = AsyncMock()
        service.llm.chat.return_value = SimpleNamespace(input_tokens=0, output_tokens=0, text='', tool_calls=[
            SimpleNamespace(name='rebuild_calendar_links', arguments={'groups': ['injected']}, id='call1')])
        with patch('modules.assistant.services._build_system_prompt', return_value='test'):
            result = await service.chat(user_id=42, message='Пересобери ссылки', is_admin=True)
        self.assertEqual(len(result.pending_action.preview['lines']), 2)
        payload = _decode_action_token(result.pending_action.action_token)
        self.assertEqual(payload['args']['groups'], sub.prepare_links(self.db)['groups'])
        self.assertEqual(self.db.query(CalendarSubscription).count(), 0)
        response = await service.execute_pending(user_id=42, action_token=result.pending_action.action_token, is_admin=True)
        self.assertEqual(response['result']['count'], 2)
        replay = await service.execute_pending(user_id=42, action_token=result.pending_action.action_token, is_admin=True)
        self.assertEqual(replay, response)
        with self.assertRaises(HTTPException):
            await service.execute_pending(user_id=42, action_token=result.pending_action.action_token, is_admin=False)
        with self.assertRaises(ValueError):
            await service.execute_pending(user_id=43, action_token=result.pending_action.action_token, is_admin=True)

    async def test_nonadmin_cannot_prepare_link_publication(self):
        service = AssistantService(self.db)
        service.llm = AsyncMock()
        service.llm.chat.return_value = SimpleNamespace(input_tokens=0, output_tokens=0, text='', tool_calls=[
            SimpleNamespace(name='rebuild_calendar_links', arguments={}, id='call1')])
        with patch('modules.assistant.services._build_system_prompt', return_value='test'), \
                patch.object(sub, 'read_roster', side_effect=AssertionError('must not read')):
            result = await service.chat(user_id=42, message='Пересобери ссылки', is_admin=False)
        self.assertIsNone(result.pending_action)
        self.assertIn('администратор', result.reply)

    def test_migration_adds_metadata_without_losing_old_events(self):
        event_id = self.event('Старое событие').id
        self.db.close()
        with self.engine.begin() as conn:
            for column in ('is_all_day', 'google_html_link', 'recurring_event_id'):
                conn.execute(text(f'ALTER TABLE calendar_events DROP COLUMN {column}'))
        with patch('main.engine', self.engine):
            main.run_migrations()
            main.run_migrations()
        self.assertEqual(self.db.get(CalendarEvent, event_id).title, 'Старое событие')
        columns = {column['name'] for column in inspect(self.engine).get_columns('calendar_events')}
        self.assertTrue({'is_all_day', 'google_html_link', 'recurring_event_id'} <= columns)
