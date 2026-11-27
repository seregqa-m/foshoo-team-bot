import copy
import base64
import json
from io import BytesIO
from PIL import Image
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from core.time import local_now
    from modules.planning import repertoire_sharing as sharing
    from modules.planning.models import RepertoireShare
    from modules.planning.repertoire import Rules, ShowRule, RepertoireProblem
    from modules.planning.repertoire_search import search_page
    from modules.planning.router import router
    from modules.theater.models import TheaterChat, TheaterShow
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class RepertoireShareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.chat = -1001234567890
        self.db.add(TheaterShow(name='Урод', normalized_name='урод', telegram_chat_id=self.chat))
        self.db.commit()
        self.request = SimpleNamespace(state=SimpleNamespace(telegram_user=SimpleNamespace(id=42), is_superadmin=False))
        self.bot = SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(type='supergroup', title='Театр')),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=17)),
            send_document=AsyncMock(return_value=SimpleNamespace(message_id=18)),
            send_photo=AsyncMock(return_value=SimpleNamespace(message_id=17)))
        self.source = {'month': '2032-06', 'fingerprint': 'share-test', 'warnings': [], 'fixed': [],
            'shows': [{'key': '1', 'name': 'Урод'}], 'slots': [
                {'date': day, 'blocked': '', 'shows': [{'key': '1', 'show': 'Урод', 'incomplete': False,
                    'status': 'ready', 'roles': [{'name': 'Летте', 'actors': [{'name': 'Анна', 'status': 'yes'}]}]}]}
                for day in ('2032-06-05', '2032-06-19')]}
        self.rules = Rules(shows=[ShowRule(key='1', count=1)])
        page = search_page(RepertoireProblem(self.source, self.rules, local_now().date()))
        self.variant = page['variants'][-1]
        self.req = sharing.PreviewRequest(month='2032-06', search_id=page['search_id'], variant_id=self.variant['id'],
            chat_id=self.chat, expected_fingerprint=self.source['fingerprint'], expected_revision=3)
        for target, kwargs in [
            ('modules.planning.repertoire_sharing.get_bot', {'return_value': self.bot}),
            ('modules.planning.repertoire_sharing.GROUP_CHAT_ID', {'new': None}),
            ('modules.planning.repertoire_router.snapshot', {'side_effect': lambda *a, **k: copy.deepcopy(self.source)}),
            ('modules.planning.repertoire_sharing.get_rules', {'side_effect': lambda *a: (self.rules, 3, 0)}),
        ]:
            patcher = patch(target, **kwargs); patcher.start(); self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    async def preview(self):
        return await sharing.preview_share(self.req, self.request, self.db)

    async def send(self, preview):
        return await sharing.send_share(sharing.SendRequest(preview_id=preview['id']), self.request, self.db)

    def assert_photo(self, preview, chat):
        self.bot.send_photo.assert_awaited_once()
        kwargs = self.bot.send_photo.call_args.kwargs
        self.assertEqual(kwargs['chat_id'], chat)
        self.assertEqual(kwargs['caption'], preview['caption'])
        raw = base64.b64decode(preview['image'].split(',', 1)[1])
        self.assertEqual(kwargs['photo'].data, raw)
        image = Image.open(BytesIO(raw))
        self.assertEqual(image.format, 'PNG')
        self.assertEqual(image.width, 1400)
        self.assertLessEqual(image.width + image.height, 10000)
        self.bot.send_message.assert_not_awaited()
        self.bot.send_document.assert_not_awaited()

    async def test_preview_uses_selected_server_variant_and_sends_only_on_explicit_action(self):
        preview = await self.preview()
        self.bot.send_photo.assert_not_awaited()
        self.assertEqual(preview['status'], 'preview')
        self.assertIn(str(int(self.variant['entries'][0]['date'][-2:])) + ' июн', preview['text'])
        self.assertIn('Урод', preview['text'])
        self.assertIn('в 19:00', preview['text'])
        sent = await self.send(preview)
        self.assertEqual(sent['status'], 'sent')
        self.assert_photo(preview, self.chat)
        self.assertEqual(sent['link'], 'https://t.me/c/1234567890/17')
        self.assertEqual((await self.send(preview))['status'], 'sent')
        self.assertEqual((await self.preview())['status'], 'sent')
        self.assertEqual(self.bot.send_photo.await_count, 1)

    async def test_changed_answers_rules_and_expiry_block_send(self):
        preview = await self.preview()
        self.source['fingerprint'] = 'changed'
        with self.assertRaises(HTTPException) as error:
            await self.send(preview)
        self.assertEqual(error.exception.status_code, 409)
        self.source['fingerprint'] = 'share-test'
        self.rules.shows[0].count = 2
        with self.assertRaises(HTTPException):
            await self.send(preview)
        self.rules.shows[0].count = 1
        row = self.db.get(RepertoireShare, preview['id'])
        row.expires_at = datetime.utcnow() - timedelta(seconds=1); self.db.commit()
        with self.assertRaises(HTTPException):
            await self.send(preview)
        self.bot.send_photo.assert_not_awaited()

    async def test_forged_variant_and_outdated_search_cannot_be_previewed(self):
        self.req.variant_id = '0' * 64
        with self.assertRaises(HTTPException):
            await self.preview()
        self.req.variant_id = self.variant['id']; self.req.expected_revision = 2
        with self.assertRaises(HTTPException):
            await self.preview()
        self.assertEqual(self.db.query(RepertoireShare).count(), 0)

    async def test_unconnected_chat_non_admin_and_foreign_preview_are_rejected(self):
        self.req.chat_id = -123
        with self.assertRaises(HTTPException):
            await self.preview()
        self.req.chat_id = self.chat
        preview = await self.preview()
        self.bot.get_chat_member.return_value.status = 'member'
        with self.assertRaises(HTTPException) as error:
            await self.send(preview)
        self.assertEqual(error.exception.status_code, 403)
        self.request.state.telegram_user.id = 43
        with self.assertRaises(HTTPException) as error:
            await self.send(preview)
        self.assertEqual(error.exception.status_code, 404)
        self.bot.send_photo.assert_not_awaited()

    async def test_uncertain_delivery_persists_and_never_replays(self):
        preview = await self.preview()
        self.bot.send_photo.side_effect = TimeoutError()
        self.assertEqual((await self.send(preview))['status'], 'unknown')
        self.db.close(); self.db = sessionmaker(bind=self.engine)()
        self.assertEqual((await self.send(preview))['status'], 'unknown')
        self.assertEqual((await self.preview())['status'], 'unknown')
        self.assertEqual(self.bot.send_photo.await_count, 1)

    async def test_delivery_claim_precedes_telegram_and_blocks_second_request(self):
        preview = await self.preview()
        async def in_flight(**kwargs):
            self.assertEqual(self.db.get(RepertoireShare, preview['id']).status, 'sending')
            self.assertEqual((await self.send(preview))['status'], 'sending')
            return SimpleNamespace(message_id=17)
        self.bot.send_photo.side_effect = in_flight
        self.assertEqual((await self.send(preview))['status'], 'sent')
        self.assertEqual(self.bot.send_photo.await_count, 1)

    async def test_confirmed_failure_can_retry_but_rate_limit_cannot_be_bypassed_by_preview(self):
        preview = await self.preview()
        method = SendMessage(chat_id=self.chat, text='test')
        self.bot.send_photo.side_effect = TelegramRetryAfter(method=method, message='wait', retry_after=60)
        self.assertEqual((await self.send(preview))['status'], 'failed')
        await self.preview()
        with self.assertRaises(HTTPException) as error:
            await self.send(preview)
        self.assertEqual(error.exception.status_code, 429)
        row = self.db.get(RepertoireShare, preview['id']); row.retry_after = None; self.db.commit()
        self.bot.send_photo.side_effect = TelegramBadRequest(method=method, message='blocked')
        self.assertEqual((await self.send(preview))['status'], 'failed')
        self.bot.send_photo.side_effect = None
        self.assertEqual((await self.send(preview))['status'], 'sent')

    async def test_long_plan_is_still_one_calendar_photo(self):
        self.source['warnings'] = ['Проверить ' * 500]
        preview = await self.preview()
        self.assertEqual(preview['delivery'], 'photo')
        self.assertEqual((await self.send(preview))['status'], 'sent')
        self.assert_photo(preview, self.chat)

    async def test_pending_legacy_text_requires_a_new_calendar_preview(self):
        preview = await self.preview()
        row = self.db.get(RepertoireShare, preview['id'])
        payload = json.loads(row.payload)
        payload['delivery'] = 'message'
        payload.pop('image')
        row.payload = json.dumps(payload)
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.send(preview)
        self.assertEqual(error.exception.status_code, 409)
        self.bot.send_message.assert_not_awaited()
        self.bot.send_photo.assert_not_awaited()

    async def test_stored_image_survives_restart_without_rerendering(self):
        preview = await self.preview()
        self.db.close()
        self.db = sessionmaker(bind=self.engine)()
        with patch.object(sharing, 'calendar_image', side_effect=AssertionError('must send frozen image')):
            self.assertEqual((await self.send(preview))['status'], 'sent')
        self.assert_photo(preview, self.chat)

    async def test_chat_list_excludes_non_admin_and_failed_checks(self):
        self.assertEqual((await sharing.share_chats(self.request, self.db))['chats'], [{'id': self.chat, 'title': 'Театр'}])
        self.bot.get_chat_member.return_value.status = 'member'
        self.assertEqual((await sharing.share_chats(self.request, self.db))['chats'], [])
        self.bot.get_chat_member.side_effect = TimeoutError()
        self.assertTrue((await sharing.share_chats(self.request, self.db))['warning'])

    async def test_registered_coordination_group_needs_no_show_mapping(self):
        coordination_chat = -1002495894419
        self.db.add(TheaterChat(telegram_chat_id=coordination_chat, title='Согласование афиши'))
        self.db.commit()
        self.assertEqual(sharing.destinations(self.db)[coordination_chat], 'Согласование афиши')
        chats = await sharing.share_chats(self.request, self.db)
        self.assertIn(coordination_chat, {chat['id'] for chat in chats['chats']})
        self.req.chat_id = coordination_chat
        preview = await self.preview()
        self.bot.send_photo.assert_not_awaited()
        sent = await self.send(preview)
        self.assertEqual(sent['status'], 'sent')
        self.assert_photo(preview, coordination_chat)
        self.assertEqual(self.db.query(TheaterShow).one().telegram_chat_id, self.chat)

    async def test_standalone_group_still_checks_admin_and_chat_type(self):
        self.db.add(TheaterChat(telegram_chat_id=-987, title='Согласование'))
        self.db.commit()
        self.req.chat_id = -987
        self.bot.get_chat_member.return_value.status = 'member'
        with self.assertRaises(HTTPException) as error:
            await self.preview()
        self.assertEqual(error.exception.status_code, 403)
        self.request.state.is_superadmin = True
        self.assertEqual((await self.preview())['status'], 'preview')
        self.bot.get_chat.return_value.type = 'channel'
        with self.assertRaises(HTTPException) as error:
            await self.preview()
        self.assertEqual(error.exception.status_code, 403)
        self.bot.send_photo.assert_not_awaited()

    def test_partial_plan_and_soft_warnings_are_in_message(self):
        variant = copy.deepcopy(self.variant)
        variant.update(missing=[{'name': 'Любовь Громова', 'count': 1}],
            spread_warnings=[{'name': 'Урод', 'dates': ['2032-06-05', '2032-06-12'], 'gap': 7, 'desired': 14}],
            load_warnings=[{'actor': 'Анна', 'dates': ['2032-06-05', '2032-06-06', '2032-06-07']}])
        text = sharing.message_text('2032-06', variant, 2, ['Нет ответа'])
        for expected in ['1 из 2', 'Не хватает: Любовь Громова — 1', 'Разнос: Урод', 'Нагрузка: Анна', 'Нет ответа']:
            self.assertIn(expected, text)

    def test_all_share_routes_inherit_admin_guard(self):
        app = FastAPI(); app.include_router(router)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/planning/repertoire/chats').status_code, 403)
            for path, payload in [('preview', self.req.model_dump()), ('send', {'preview_id': '0' * 64})]:
                self.assertEqual(client.post('/api/planning/repertoire/share/' + path, json=payload).status_code, 403)
        self.bot.send_photo.assert_not_awaited()
