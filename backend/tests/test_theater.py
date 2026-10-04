import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core import access
    from core.database import Base, get_db
    from modules.admin.services import bootstrap_superadmin, change_role
    from modules.admin.models import AppUser, SuperAdmin
    from modules.theater.models import TheaterAudit, TheaterChat, TheaterShow
    from modules.theater.router import router
    from modules.theater.services import inspect_chat, set_show

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def headers(user_id=42):
    fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': user_id})}
    key = hmac.new(b'WebAppData', access.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data': urlencode(fields)}


class TheaterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{self.directory.name}/test.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        with self.Session() as db:
            bootstrap_superadmin(db, 42)
        for patcher in [patch('modules.admin.services.SessionLocal', self.Session),
                        patch('core.access._is_group_admin', AsyncMock(return_value=True)),
                        patch('modules.theater.router.inspect_chat', AsyncMock(return_value='Чат спектакля'))]:
            patcher.start()
            self.addCleanup(patcher.stop)
        access._access_cache.clear()
        app = FastAPI()
        app.include_router(router, dependencies=[Depends(access.authorize_api)])

        def database():
            with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.directory.cleanup()
        access._access_cache.clear()

    def catalog(self):
        response = self.client.get('/api/admin/theater', headers=headers())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, payload=None):
        return self.client.post('/api/admin/theater' + path, headers=headers(), json=payload)

    def save(self, show, chat_id=-1001, name=None):
        return self.client.put(f'/api/admin/theater/shows/{show["id"]}', headers=headers(), json={
            'name': name or show['name'], 'telegram_chat_id': chat_id, 'expected_revision': show['revision']})

    def test_signed_superadmin_only_even_for_reads(self):
        self.assertEqual(self.client.get('/api/admin/theater').status_code, 401)
        for method, path, body in [('get', '', None), ('post', '/shows', {'name': 'Урод'}),
                                   ('post', '/chats', {'telegram_chat_id': -1001}),
                                   ('post', '/shows/import', None),
                                   ('put', '/shows/1', {'name': 'Урод', 'expected_revision': 0})]:
            kwargs = {'headers': headers(84)}
            if body is not None:
                kwargs['json'] = body
            response = getattr(self.client, method)('/api/admin/theater' + path, **kwargs)
            self.assertEqual(response.status_code, 403, response.text)

    def test_common_catalog_deduplicates_normalized_names(self):
        self.assertEqual(self.post('/shows', {'name': '  Урод  '}).json()['added'], 1)
        self.assertEqual(self.post('/shows', {'name': 'УРОД'}).json()['added'], 0)
        self.assertEqual(self.post('/shows', {'name': '   '}).status_code, 422)
        self.assertEqual([s['name'] for s in self.catalog()['shows']], ['Урод'])

    def test_import_is_repeatable_and_preserves_routes(self):
        self.post('/shows', {'name': 'Урод'})
        self.assertEqual(self.post('/chats', {'telegram_chat_id': -1001}).status_code, 200)
        self.assertEqual(self.save(self.catalog()['shows'][0]).status_code, 200)
        with patch('modules.theater.router.read_sheet_names', return_value=['УРОД', 'Слепые']):
            self.assertEqual(self.post('/shows/import').json()['added'], 1)
            self.assertEqual(self.post('/shows/import').json()['added'], 0)
        shows = {s['name']: s for s in self.catalog()['shows']}
        self.assertEqual(shows['Урод']['telegram_chat_id'], -1001)
        self.assertIsNone(shows['Слепые']['telegram_chat_id'])

    def test_route_update_remove_and_stale_editor(self):
        self.post('/shows', {'name': 'Урод'})
        self.post('/chats', {'telegram_chat_id': -1001})
        original = self.catalog()['shows'][0]
        updated = self.save(original).json()
        self.assertEqual(updated['revision'], 1)
        self.assertEqual(self.save(original, None).status_code, 409)
        self.assertEqual(self.save(updated, None).status_code, 200)
        self.assertIsNone(self.catalog()['shows'][0]['telegram_chat_id'])
        self.assertEqual(sum(a['action'] == 'show_updated' for a in self.catalog()['audit']), 2)

    def test_existing_show_identity_survives_rename_and_duplicate_is_rejected(self):
        self.post('/shows', {'name': 'Урод'})
        self.post('/shows', {'name': 'Слепые'})
        show = next(s for s in self.catalog()['shows'] if s['name'] == 'Урод')
        self.assertEqual(self.save(show, None, 'СЛЕПЫЕ').status_code, 409)
        updated = self.save(show, None, 'Урод — новая редакция').json()
        self.assertEqual(updated['id'], show['id'])
        with patch('modules.theater.router.read_sheet_names', return_value=['Урод']):
            self.assertEqual(self.post('/shows/import').json()['added'], 0)
        self.assertEqual(len(self.catalog()['shows']), 2)

    def test_unknown_chat_and_telegram_failure_leave_route_intact(self):
        self.post('/shows', {'name': 'Урод'})
        show = self.catalog()['shows'][0]
        self.assertEqual(self.save(show).status_code, 404)
        with patch('modules.theater.router.inspect_chat', AsyncMock(side_effect=HTTPException(502, 'offline'))):
            self.assertEqual(self.post('/chats', {'telegram_chat_id': -1001}).status_code, 502)
        self.assertEqual(self.catalog()['chats'], [])
        self.post('/chats', {'telegram_chat_id': -1001})
        with patch('modules.theater.router.inspect_chat', AsyncMock(side_effect=HTTPException(400, 'bot removed'))):
            self.assertEqual(self.save(show).status_code, 400)
        self.assertIsNone(self.catalog()['shows'][0]['telegram_chat_id'])

    def test_chat_id_validation_and_registration_is_idempotent(self):
        for value in [True, 123, '-1001', 0, -(2**53)]:
            self.assertEqual(self.post('/chats', {'telegram_chat_id': value}).status_code, 422)
        for _ in range(2):
            self.assertEqual(self.post('/chats', {'telegram_chat_id': -1001}).status_code, 200)
        data = self.catalog()
        self.assertEqual(len(data['chats']), 1)
        self.assertEqual(sum(a['action'] == 'chat_registered' for a in data['audit']), 1)

    def test_revocation_during_telegram_check_prevents_registration(self):
        async def revoke(*args):
            with self.Session() as db:
                db.add(AppUser(telegram_user_id=84))
                db.add(SuperAdmin(telegram_user_id=84, granted_by=42))
                db.commit()
                change_role(db, 84, 42, False)
            return 'Чат'
        with patch('modules.theater.router.inspect_chat', side_effect=revoke):
            self.assertEqual(self.post('/chats', {'telegram_chat_id': -1001}).status_code, 403)
        with self.Session() as db:
            self.assertEqual(db.query(TheaterChat).count(), 0)

    def test_service_rechecks_revoked_role_even_with_cached_identity(self):
        self.post('/shows', {'name': 'Урод'})
        show = self.catalog()['shows'][0]
        with self.Session() as db:
            role = db.get(SuperAdmin, 42)
            with self.Session() as other:
                other.add(AppUser(telegram_user_id=84))
                other.add(SuperAdmin(telegram_user_id=84, granted_by=42))
                other.commit()
                change_role(other, 84, 42, False)
            self.assertIsNotNone(role)
            with self.assertRaises(HTTPException) as error:
                set_show(db, 42, show['id'], 'Изменение', None, 0)
            self.assertEqual(error.exception.status_code, 403)
            self.assertEqual(db.get(TheaterShow, show['id']).name, 'Урод')


class TelegramInspectionTests(unittest.TestCase):
    def test_requires_group_and_pin_right_and_never_sends_messages(self):
        for kind, status, pin, accepted in [('private', 'administrator', True, False),
                                          ('channel', 'administrator', True, False),
                                          ('supergroup', 'member', False, False),
                                          ('supergroup', 'administrator', False, False),
                                          ('supergroup', 'administrator', True, True)]:
            bot = SimpleNamespace(id=1, get_chat=AsyncMock(return_value=SimpleNamespace(id=-1001, type=kind, title='Чат')),
                                  get_chat_member=AsyncMock(return_value=SimpleNamespace(status=status, can_pin_messages=pin)))
            if accepted:
                self.assertEqual(asyncio.run(inspect_chat(bot, -1001)), 'Чат')
            else:
                with self.assertRaises(HTTPException):
                    asyncio.run(inspect_chat(bot, -1001))

    def test_api_failure_is_sanitized(self):
        bot = SimpleNamespace(id=1, get_chat=AsyncMock(side_effect=RuntimeError('secret-token')))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(inspect_chat(bot, -1001))
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('secret-token', error.exception.detail)
