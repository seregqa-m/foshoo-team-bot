import hashlib
import hmac
import json
import os
import time
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://'}, clear=True), patch('dotenv.load_dotenv'):
    from core.access import authorize_api, verify_init_data
    from core.database import Base, get_db
    from modules.attendance.models import DayAnswer, AnswerHistory
    from modules.attendance.router import router
    from modules.attendance.services import record_answers, planning_answers, export_pending
    from modules.planning.services import build_plan
    import modules.theater.models

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def signed_headers(user_id=42):
    fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': user_id, 'username': 'actor'})}
    key = hmac.new(b'WebAppData', b'test-token', hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data': urlencode(fields)}


class PersonalAttendanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.day = date(2026, 12, 19)
        self.other_day = date(2026, 12, 20)
        record_answers(self.db, 42, 'actor', 'availability:1', {self.day: 'no', self.other_day: 'yes'})
        record_answers(self.db, 99, 'another', 'availability:1', {self.day: 'no'})
        self.db.commit()
        app = FastAPI()
        app.include_router(router, dependencies=[Depends(authorize_api)])
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        for p in [patch('core.access._permissions', AsyncMock(return_value=(True, False, False))),
                  patch('core.access.verify_init_data', side_effect=lambda raw: verify_init_data(raw, bot_token='test-token')),
                  patch('modules.attendance.router.local_now', return_value=datetime(2026, 11, 17))]:
            p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        self.client.close(); self.db.close(); self.engine.dispose()

    def save(self, answer='yes', revision=1, **extra):
        return self.client.put('/api/attendance/me', headers=signed_headers(), json={
            'date': self.day.isoformat(), 'answer': answer, 'expected_revision': revision, **extra,
        })

    def current(self):
        self.db.expire_all()
        return self.db.get(DayAnswer, (42, self.day))

    def test_default_month_and_personal_visibility(self):
        result = self.client.get('/api/attendance/me', headers=signed_headers()).json()
        self.assertEqual(result['month'], '2026-12')
        self.assertEqual(len(result['days']), 2)
        self.assertEqual(result['days'][0], {'date': '2026-12-19', 'answer': 'no', 'revision': 1, 'editable': True})
        self.assertEqual(self.client.get('/api/attendance/me?month=2027-01', headers=signed_headers()).json()['days'], [])
        for month in ['2026-13', '2026-1', 'invalid']:
            self.assertEqual(self.client.get('/api/attendance/me', params={'month': month}, headers=signed_headers()).status_code, 422)

    def test_member_can_change_only_own_date_without_open_poll(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.current().answer, 'yes')
        self.assertEqual(self.current().revision, 2)
        self.assertEqual(self.db.get(DayAnswer, (42, self.other_day)).revision, 1)
        self.assertEqual(self.db.get(DayAnswer, (99, self.day)).answer, 'no')
        self.assertEqual(self.db.query(AnswerHistory).count(), 4)

    def test_unsigned_nonmember_and_spoofed_requests_rejected(self):
        self.assertEqual(self.client.get('/api/attendance/me').status_code, 401)
        self.assertEqual(self.client.put('/api/attendance/me', json={}).status_code, 401)
        self.assertEqual(self.save(user_id=99).status_code, 403)
        self.assertEqual(self.save(username='another').status_code, 403)
        with patch('core.access._permissions', AsyncMock(return_value=(False, False, False))):
            self.assertEqual(self.save().status_code, 403)
        self.assertEqual(self.current().answer, 'no')

    def test_retry_is_idempotent_but_cannot_overwrite_newer_poll(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.current().revision, 2)
        record_answers(self.db, 42, 'actor', 'poll:2', {self.day: 'no'})
        self.db.commit()
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.current().answer, 'no')
        self.assertEqual(self.save(revision=3).status_code, 200)
        self.assertEqual(self.current().answer, 'yes')

    def test_replayed_poll_and_other_day_change_do_not_undo_personal_answer(self):
        self.assertEqual(self.save().status_code, 200)
        record_answers(self.db, 42, 'actor', 'availability:1', {self.day: 'no', self.other_day: 'no'})
        self.db.commit()
        self.assertEqual(self.current().answer, 'yes')
        record_answers(self.db, 42, 'actor', 'availability:1', {self.day: 'retracted', self.other_day: 'retracted'})
        self.db.commit()
        self.assertEqual(self.current().answer, 'yes')

    def test_unknown_and_retracted_are_displayed_correctly(self):
        self.assertEqual(self.save('unknown').status_code, 200)
        self.assertEqual(self.current().answer, 'unknown')
        record_answers(self.db, 42, 'actor', 'poll:3', {self.day: 'maybe'})
        record_answers(self.db, 42, 'actor', 'availability:1', {self.day: 'no', self.other_day: 'retracted'})
        self.db.commit()
        days = self.client.get('/api/attendance/me', headers=signed_headers()).json()['days']
        self.assertEqual([d['answer'] for d in days], ['unknown', None])

    def test_past_missing_and_invalid_answers_are_not_written(self):
        self.assertEqual(self.save(answer='retracted').status_code, 422)
        self.assertEqual(self.save(revision=0).status_code, 422)
        self.assertEqual(self.save(date='2027-01-01').status_code, 404)
        with patch('modules.attendance.router.local_now', return_value=datetime(2026, 12, 20)):
            self.assertEqual(self.save().status_code, 422)
            days = self.client.get('/api/attendance/me?month=2026-12', headers=signed_headers()).json()['days']
            self.assertFalse(days[0]['editable'])
        self.assertEqual(self.current().revision, 1)

    def test_planning_sees_change_before_export_and_export_failure_keeps_it(self):
        self.assertEqual(self.save().status_code, 200)
        sheets = MagicMock()
        sheets.get_actor_mapping.return_value = {'actor': 'Актёр'}
        source = {'casts': [['Спектакль', 'Роль', 'Актёр'], ['Шоу', 'Роль', 'Актёр']],
                  'schedule': [['Имя', '19 дек 2026'], ['', ''], ['Актёр', 'нет']],
                  'availability': planning_answers(self.db, '2026-12', sheets)}
        self.assertEqual(build_plan(source, '2026-12')['slots'][0]['shows'][0]['status'], 'ready')
        sheets.record_poll_answer.side_effect = OSError('offline')
        with patch('config.GOOGLE_SHEETS_ID', 'test'), patch('config.GOOGLE_CALENDAR_JSON', '/test'), \
                patch('modules.attendance.services.os.path.exists', return_value=True), \
                patch('sheets_client.SheetsClient', return_value=sheets):
            with self.assertLogs('modules.attendance.services', level='ERROR'):
                export_pending(self.db)
            self.assertEqual(self.current().answer, 'yes')
            self.assertLess(self.current().exported_revision, self.current().revision)
            sheets.record_poll_answer.side_effect = None
            sheets.record_poll_answer.return_value = True
            export_pending(self.db)
            self.assertEqual(self.current().exported_revision, self.current().revision)
