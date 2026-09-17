import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core import access
    from core.database import Base, get_db
    from auth_router import router as auth_router
    from modules.admin.models import AppUser, SuperAdmin, AdminAudit
    from modules.admin.router import router
    from modules.admin.services import bootstrap_superadmin, change_role, remember_identity

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def headers(user_id=42, username='sergey', first_name='Сергей'):
    fields = {'auth_date': str(int(time.time())), 'user': json.dumps({
        'id': user_id, 'username': username, 'first_name': first_name})}
    key = hmac.new(b'WebAppData', access.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data': urlencode(fields)}


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{self.directory.name}/test.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        for patcher in [patch('modules.admin.services.SessionLocal', self.Session),
                        patch('core.access._is_group_admin', AsyncMock(return_value=False)),
                        patch('core.access._known_actor', return_value=False)]:
            patcher.start()
            self.addCleanup(patcher.stop)
        access._access_cache.clear()
        with self.Session() as db:
            bootstrap_superadmin(db, 42)
        app = FastAPI()
        app.include_router(auth_router, dependencies=[Depends(access.authorize_api)])
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

    def register(self, user_id=84, username='masha', name='Маша'):
        remember_identity(access.TelegramUser(user_id, username, name))

    def grant(self, user_id=84):
        self.register(user_id)
        response = self.client.post('/api/admin/superadmins', headers=headers(), json={'telegram_user_id': user_id})
        self.assertEqual(response.status_code, 200, response.text)

    def test_bootstrap_is_one_time_and_does_not_restore_revoked_role(self):
        self.grant()
        with self.Session() as db:
            change_role(db, 84, 42, False)
            self.assertFalse(bootstrap_superadmin(db, 42))
            self.assertFalse(bootstrap_superadmin(db, 999))
            self.assertIsNone(db.get(SuperAdmin, 42))
            self.assertIsNone(db.get(SuperAdmin, 999))
            self.assertEqual(db.query(SuperAdmin).count(), 1)
            self.assertEqual([a.action for a in db.query(AdminAudit).order_by(AdminAudit.id)], ['bootstrap', 'grant', 'revoke'])

    def test_last_role_cannot_be_removed_and_transaction_recovers(self):
        response = self.client.delete('/api/admin/superadmins/42', headers=headers())
        self.assertEqual(response.status_code, 409)
        self.grant()
        self.assertEqual(self.client.delete('/api/admin/superadmins/42', headers=headers()).status_code, 200)

    def test_concurrent_self_revocation_keeps_one_admin(self):
        self.grant()
        barrier = threading.Barrier(2)

        def revoke(user_id):
            with self.Session() as db:
                barrier.wait(timeout=5)
                try:
                    change_role(db, user_id, user_id, False)
                    return 200
                except HTTPException as exc:
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(revoke, [42, 84])), [200, 409])
        with self.Session() as db:
            self.assertEqual(db.query(SuperAdmin).count(), 1)

    def test_revoked_caller_is_rechecked_despite_cached_orm_identity(self):
        self.grant()
        self.register(99)
        with self.Session() as stale, self.Session() as other:
            stale_role = stale.get(SuperAdmin, 42)
            self.assertIsNotNone(stale_role)
            change_role(other, 84, 42, False)
            with self.assertRaises(HTTPException) as error:
                change_role(stale, 42, 99, True)
            self.assertEqual(error.exception.status_code, 403)
            self.assertIsNone(other.get(SuperAdmin, 99))

    def test_signed_denied_entry_registers_identity_but_invalid_signature_does_not(self):
        self.assertEqual(self.client.get('/api/auth/check', headers=headers(84, 'masha', 'Маша')).status_code, 403)
        bad = headers(99)
        bad['X-Telegram-Init-Data'] += '&user_id=42'
        self.assertEqual(self.client.get('/api/auth/check', headers=bad).status_code, 401)
        with self.Session() as db:
            self.assertEqual(db.get(AppUser, 84).display_name, 'Маша')
            self.assertIsNone(db.get(AppUser, 99))
            self.assertIsNone(db.get(SuperAdmin, 84))
        response = self.client.get('/api/admin/users', headers=headers(), params={'q': 'МАША'})
        self.assertEqual([u['telegram_user_id'] for u in response.json()['users']], [84])

    def test_search_by_username_id_and_literal_wildcards(self):
        self.register()
        self.register(99, 'a_b', 'Ольга')
        for query, expected in [('@MASHA', [84]), ('84', [84]), ('a_', [99]), ('%%', [])]:
            response = self.client.get('/api/admin/users', headers=headers(), params={'q': query})
            self.assertEqual([u['telegram_user_id'] for u in response.json()['users']], expected)

    def test_group_admin_cannot_manage_global_roles_or_spoof_them(self):
        self.register()
        with patch('core.access._is_group_admin', AsyncMock(return_value=True)):
            auth = self.client.get('/api/auth/check', headers=headers(84)).json()
            self.assertTrue(auth['is_admin'])
            self.assertFalse(auth['is_superadmin'])
            for method, path, options in [
                ('get', '/api/admin/superadmins', {}), ('get', '/api/admin/users?q=sergey', {}),
                ('post', '/api/admin/superadmins', {'json': {'telegram_user_id': 84, 'is_superadmin': True}}),
                ('delete', '/api/admin/superadmins/42', {}),
            ]:
                self.assertEqual(getattr(self.client, method)(path, headers=headers(84), **options).status_code, 403)

    def test_global_access_does_not_need_sheets_and_revocation_is_immediate(self):
        self.grant()
        with patch('core.access._known_actor', side_effect=HTTPException(503, 'offline')):
            auth = self.client.get('/api/auth/check', headers=headers()).json()
            self.assertTrue(auth['is_superadmin'])
        with self.Session() as db:
            change_role(db, 84, 42, False)
        with patch('core.access._known_actor', return_value=True):
            auth = self.client.get('/api/auth/check', headers=headers()).json()
            self.assertFalse(auth['is_superadmin'])
            self.assertFalse(auth['is_admin'])
            self.assertEqual(self.client.get('/api/admin/superadmins', headers=headers()).status_code, 403)

    def test_grant_requires_known_user_and_replays_do_not_duplicate_audit(self):
        response = self.client.post('/api/admin/superadmins', headers=headers(), json={'telegram_user_id': 84})
        self.assertEqual(response.status_code, 404)
        self.grant()
        self.grant()
        for _ in range(2):
            self.assertEqual(self.client.delete('/api/admin/superadmins/84', headers=headers()).status_code, 200)
        with self.Session() as db:
            self.assertEqual([a.action for a in db.query(AdminAudit).order_by(AdminAudit.id)], ['bootstrap', 'grant', 'revoke'])

    def test_changed_username_keeps_role_and_updates_search(self):
        self.grant()
        self.assertEqual(self.client.get('/api/auth/check', headers=headers(84, 'new_masha', 'Мария')).status_code, 200)
        found = self.client.get('/api/admin/users?q=МАРИЯ', headers=headers()).json()['users']
        self.assertEqual(found[0]['telegram_user_id'], 84)
        self.assertTrue(found[0]['is_superadmin'])
        self.assertTrue(asyncio.run(access.is_admin(84)))

    def test_simultaneous_first_open_registers_one_identity(self):
        barrier = threading.Barrier(2)

        def before_insert(mapper, connection, target):
            if target.telegram_user_id == 84:
                barrier.wait(timeout=5)
        event.listen(AppUser, 'before_insert', before_insert)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: self.register(), range(2)))
        finally:
            event.remove(AppUser, 'before_insert', before_insert)
        with self.Session() as db:
            self.assertEqual(db.query(AppUser).filter_by(telegram_user_id=84).count(), 1)
            self.assertEqual(db.get(AppUser, 84).display_name, 'Маша')

    def test_unsigned_admin_endpoints_rejected(self):
        self.assertEqual(self.client.get('/api/admin/superadmins').status_code, 401)
        self.assertEqual(self.client.get('/api/admin/users?q=sergey').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/superadmins', json={'telegram_user_id': 84}).status_code, 401)
        self.assertEqual(self.client.delete('/api/admin/superadmins/42').status_code, 401)
