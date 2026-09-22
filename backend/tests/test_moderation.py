import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://',
                             'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from modules.moderation.models import ModerationComment
    from modules.moderation.services import ModerationService, classify
    from bot import dp, bot as app_bot, handle_group_message

from aiogram.types import Message, Update, User, Chat
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

CHANNEL, DISCUSSION = -100100, -100200


def message(**kwargs):
    return Message(**{
        'message_id': 20, 'date': datetime.now(timezone.utc),
        'chat': Chat(id=DISCUSSION, type='supergroup'),
        'from_user': User(id=10, is_bot=False, first_name='Автор', username='author'),
        'text': 'Заработок 10000 в день, пишите мне', **kwargs,
    })


class ModerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.service = ModerationService('@example_channel', 42, -100300, self.Session, auto_delete=False)
        self.bot = NS(id=999, get_chat=AsyncMock(side_effect=self.get_chat),
                      get_chat_member=AsyncMock(side_effect=self.get_member),
                      send_message=AsyncMock(return_value=NS(message_id=500)),
                      delete_message=AsyncMock(return_value=True), edit_message_text=AsyncMock())
        self.classifier = AsyncMock(return_value=(True, 'Реклама заработка в тексте'))
        mocked = patch('modules.moderation.services.classify', self.classifier)
        mocked.start()
        self.addCleanup(mocked.stop)

    def tearDown(self):
        self.engine.dispose()

    async def get_chat(self, chat):
        return NS(id=CHANNEL, type='channel', linked_chat_id=DISCUSSION) if chat == '@example_channel' else NS(
            id=DISCUSSION, type='supergroup', linked_chat_id=CHANNEL)

    async def get_member(self, chat, user):
        return NS(status='administrator' if user == self.bot.id else 'member', can_delete_messages=True)

    def state(self):
        with self.Session() as db:
            return db.query(ModerationComment).one().state

    def query(self, action='spam', revision=1, user=42, notification_id=500):
        return NS(data=f'mod:{action}:1:{revision}', from_user=NS(id=user),
                  message=NS(chat=NS(id=42, type='private'), message_id=notification_id), answer=AsyncMock())

    async def test_no_automatic_deletion_and_payload_includes_name_username_and_hidden_links(self):
        await self.service.inspect(message(entities=[{'type': 'text_link', 'offset': 0, 'length': 3, 'url': 'https://example.org'}]), self.bot, 1)
        payload = self.classifier.call_args.args[0]
        self.assertEqual(payload['sender'], {'name': 'Автор', 'username': 'author', 'kind': 'user'})
        self.assertEqual(payload['links'], ['https://example.org'])
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.state(), 'pending')
        self.assertEqual(self.bot.send_message.call_args.args[0], 42)
        self.assertIsNone(self.bot.send_message.call_args.kwargs['parse_mode'])

    async def test_caption_and_sender_channel_name_are_checked(self):
        await self.service.inspect(message(text=None, caption='Привет!', sender_chat=Chat(
            id=-100900, type='channel', title='Заработок ежедневно', username='earn_example')), self.bot, 1)
        payload = self.classifier.call_args.args[0]
        self.assertEqual(payload['text'], 'Привет!')
        self.assertEqual(payload['sender']['name'], 'Заработок ежедневно')
        self.assertEqual(payload['sender']['username'], 'earn_example')

    async def test_delete_uses_bot_api_once_even_after_restart(self):
        await self.service.inspect(message(), self.bot, 1)
        await asyncio.gather(self.service.callback(self.query(), self.bot), self.service.callback(self.query(), self.bot))
        self.bot.delete_message.assert_awaited_once_with(DISCUSSION, 20)
        self.assertEqual(self.state(), 'deleted')
        restarted = ModerationService('@example_channel', 42, -100300, self.Session, auto_delete=False)
        await restarted.callback(self.query(), self.bot)
        self.bot.delete_message.assert_awaited_once()
        self.assertNotIn('оставлен без изменений', self.bot.edit_message_text.call_args.kwargs['text'])

    async def test_keep_records_decision_and_does_not_notify_same_content_again(self):
        await self.service.inspect(message(), self.bot, 1)
        await self.service.callback(self.query('keep'), self.bot)
        await self.service.inspect(message(), self.bot, 2)
        self.assertEqual(self.state(), 'not_spam')
        self.bot.delete_message.assert_not_awaited()
        self.classifier.assert_awaited_once()
        self.bot.send_message.assert_awaited_once()

    async def test_changed_text_invalidates_old_buttons_and_old_updates_are_ignored(self):
        await self.service.inspect(message(), self.bot, 1)
        self.classifier.return_value = (False, 'Обычный отзыв')
        await self.service.inspect(message(text='Спасибо за спектакль!'), self.bot, 3)
        await self.service.inspect(message(), self.bot, 2)
        await self.service.callback(self.query(), self.bot)
        self.bot.delete_message.assert_not_awaited()
        self.assertEqual(self.state(), 'clear')
        self.assertEqual(self.classifier.await_count, 2)

    async def test_changed_sender_name_is_rechecked(self):
        self.classifier.return_value = (False, '')
        await self.service.inspect(message(text='Привет'), self.bot, 1)
        self.classifier.return_value = (True, 'Реклама в имени')
        await self.service.inspect(message(text='Привет', from_user=User(
            id=10, first_name='Заработок 10000 в день', is_bot=False)), self.bot, 2)
        self.assertEqual(self.state(), 'pending')
        self.assertEqual(self.classifier.await_count, 2)

    async def test_stranger_or_forged_notification_cannot_delete(self):
        await self.service.inspect(message(), self.bot, 1)
        await self.service.callback(self.query(user=84), self.bot)
        await self.service.callback(self.query(notification_id=501), self.bot)
        forwarded = self.query()
        forwarded.message.chat.type = 'group'
        await self.service.callback(forwarded, self.bot)
        self.bot.delete_message.assert_not_awaited()

    async def test_disabled_feature_and_other_chat_do_not_read_comments(self):
        disabled = ModerationService('', 42, session_factory=self.Session)
        self.assertFalse(await disabled.inspect(message(), self.bot, 1))
        self.bot.get_chat.assert_not_awaited()
        self.assertFalse(await self.service.inspect(message(chat=Chat(id=-100999, type='supergroup')), self.bot, 1))
        self.classifier.assert_not_awaited()

    async def test_missing_discussion_rights_and_internal_group_are_rejected(self):
        self.bot.get_chat_member.return_value = NS(status='member', can_delete_messages=False)
        self.bot.get_chat_member.side_effect = None
        self.assertIsNone(await self.service.resolve(self.bot))
        self.assertIn('права администратора', self.service.status)
        self.bot.get_chat_member.side_effect = self.get_member
        self.service.internal_chat_id = DISCUSSION
        self.assertIsNone(await self.service.resolve(self.bot, force=True))
        self.assertIn('GROUP_CHAT_ID', self.service.status)

    async def test_original_channel_posts_admin_messages_and_media_only_are_exempt(self):
        await self.service.inspect(message(is_automatic_forward=True), self.bot, 1)
        await self.service.inspect(message(sender_chat=Chat(id=CHANNEL, type='channel', title='Our channel')), self.bot, 2)
        await self.service.inspect(message(text=None), self.bot, 3)
        self.bot.get_chat_member.side_effect = None
        self.bot.get_chat_member.return_value = NS(status='administrator', can_delete_messages=True)
        await self.service.inspect(message(), self.bot, 4)
        self.classifier.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_failed_llm_or_notification_never_deletes(self):
        self.classifier.side_effect = TimeoutError()
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'check_failed')
        # Алерт улетел модератору с типом ошибки — молчать нельзя.
        alert = self.bot.send_message.call_args
        self.assertEqual(alert.args[0], 42)
        self.assertIn('Не смогла проверить', alert.args[1])
        self.assertIn('TimeoutError', alert.args[1])
        self.classifier.side_effect = None
        self.bot.send_message.side_effect = TimeoutError()
        await self.service.inspect(message(text='Другой спам'), self.bot, 2)
        self.assertEqual(self.state(), 'notification_failed')
        self.bot.delete_message.assert_not_awaited()

    async def test_uncertain_delete_does_not_repeat_or_claim_success(self):
        await self.service.inspect(message(), self.bot, 1)
        self.bot.delete_message.side_effect = TimeoutError()
        await self.service.callback(self.query(), self.bot)
        await self.service.callback(self.query(), self.bot)
        self.assertEqual(self.state(), 'delete_unknown')
        self.bot.delete_message.assert_awaited_once()
        self.assertIn('Не удалось подтвердить', self.bot.edit_message_text.call_args.kwargs['text'])

    async def test_already_deleted_message_is_handled(self):
        await self.service.inspect(message(), self.bot, 1)
        self.bot.delete_message.side_effect = TelegramBadRequest(method=DeleteMessage(chat_id=DISCUSSION, message_id=20),
                                                               message='Bad Request: message to delete not found')
        await self.service.callback(self.query(), self.bot)
        self.assertEqual(self.state(), 'deleted')
        self.assertIn('уже отсутствует', self.bot.edit_message_text.call_args.kwargs['text'])

    async def test_expired_comment_is_not_deleted(self):
        await self.service.inspect(message(date=datetime.now(timezone.utc) - timedelta(days=3)), self.bot, 1)
        await self.service.callback(self.query(), self.bot)
        self.assertEqual(self.state(), 'expired')
        self.bot.delete_message.assert_not_awaited()

    def forwarded(self, comment, sender_id=42, hidden=False):
        origin = ({'type': 'hidden_user', 'date': comment.date, 'sender_user_name': 'Скрытый Автор'}
                  if hidden else {'type': 'user', 'date': comment.date, 'sender_user': comment.from_user})
        return Message(message_id=1000, date=datetime.now(timezone.utc),
                       chat=Chat(id=sender_id, type='private'),
                       from_user=User(id=sender_id, is_bot=False, first_name='Moderator'),
                       forward_origin=origin, text=comment.text, caption=comment.caption)

    async def test_real_user_forwards_are_assessed_without_deletion_target(self):
        for hidden in (False, True):
            await self.service.manual_check(self.forwarded(message(), hidden=hidden), self.bot, 1)
            self.assertIn('Источник не подтверждён', self.bot.send_message.call_args.args[1])
            self.assertNotIn('reply_markup', self.bot.send_message.call_args.kwargs)
        self.assertEqual(self.classifier.call_args.args[0]['sender']['name'], 'Скрытый Автор')
        self.bot.delete_message.assert_not_awaited()
        with self.Session() as db:
            self.assertEqual(db.query(ModerationComment).count(), 0)

    async def test_forward_rejects_non_recipient_and_channel_posts(self):
        await self.service.manual_check(self.forwarded(message(), sender_id=84), self.bot, 1)
        post = self.forwarded(message()).model_copy(update={'forward_origin': NS(type='channel')})
        await self.service.manual_check(post, self.bot, 2)
        await self.service.manual_check(self.forwarded(message(text=None)), self.bot, 3)
        self.classifier.assert_not_awaited()
        self.bot.delete_message.assert_not_awaited()

    async def test_automatic_deletion_and_restart_do_not_repeat(self):
        self.service.auto_delete = True
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'deleted')
        self.assertIn('Спам удалён', self.bot.send_message.call_args.args[1])
        self.assertIsNone(self.bot.send_message.call_args.kwargs['reply_markup'])
        restarted = ModerationService('@example_channel', 42, -100300, self.Session)
        await restarted.inspect(message(), self.bot, 2)
        self.bot.delete_message.assert_awaited_once_with(DISCUSSION, 20)

    async def test_auto_delivery_failure_preserves_deleted_or_uncertain_state(self):
        self.service.auto_delete = True
        self.bot.send_message.side_effect = TimeoutError()
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'deleted')
        self.bot.delete_message.side_effect = TimeoutError()
        await self.service.inspect(message(message_id=21), self.bot, 2)
        await self.service.inspect(message(message_id=21), self.bot, 3)
        with self.Session() as db:
            self.assertEqual(db.query(ModerationComment).filter_by(message_id=21).one().state, 'delete_unknown')
        self.assertEqual(self.bot.delete_message.await_count, 2)

    async def test_auto_clear_failed_and_expired_comments_are_not_deleted(self):
        self.service.auto_delete = True
        self.classifier.return_value = (False, 'Обычный отзыв')
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'clear')
        self.classifier.side_effect = TimeoutError()
        await self.service.inspect(message(text='Изменение'), self.bot, 2)
        self.assertEqual(self.state(), 'check_failed')
        self.classifier.side_effect = None
        self.classifier.return_value = (True, 'Спам')
        await self.service.inspect(message(date=datetime.now(timezone.utc)-timedelta(days=3)), self.bot, 3)
        self.assertEqual(self.state(), 'expired')
        self.bot.delete_message.assert_not_awaited()

    async def test_auto_rechecks_promoted_admin_before_delete(self):
        self.service.auto_delete = True
        async def verdict(payload):
            self.bot.get_chat_member.side_effect = None
            self.bot.get_chat_member.return_value = NS(status='administrator', can_delete_messages=True)
            return True, 'Спам'
        self.classifier.side_effect = verdict
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'exempt')
        self.bot.delete_message.assert_not_awaited()

    async def test_edit_arriving_during_classification_prevents_stale_auto_delete(self):
        self.service.auto_delete = True
        entered, release = asyncio.Event(), asyncio.Event()
        async def verdict(payload):
            if payload['text'] == message().text:
                entered.set()
                await release.wait()
                return True, 'Спам'
            return False, 'Отзыв'
        self.classifier.side_effect = verdict
        first = asyncio.create_task(self.service.inspect(message(), self.bot, 1))
        await entered.wait()
        edited = asyncio.create_task(self.service.inspect(message(text='Спасибо!'), self.bot, 2))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, edited)
        self.assertEqual(self.state(), 'clear')
        self.bot.delete_message.assert_not_awaited()

    async def test_auto_rejected_delete_leaves_manual_action(self):
        self.service.auto_delete = True
        self.bot.delete_message.side_effect = TelegramBadRequest(
            method=DeleteMessage(chat_id=DISCUSSION, message_id=20), message='not enough rights')
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'pending')
        self.assertIn('отклонил', self.bot.send_message.call_args.args[1])
        self.assertIsNotNone(self.bot.send_message.call_args.kwargs['reply_markup'])

    async def test_auto_lost_permissions_prevent_delete(self):
        self.service.auto_delete = True
        async def verdict(payload):
            self.bot.get_chat_member.side_effect = None
            self.bot.get_chat_member.return_value = NS(status='member', can_delete_messages=False)
            return True, 'Спам'
        self.classifier.side_effect = verdict
        await self.service.inspect(message(), self.bot, 1)
        self.assertEqual(self.state(), 'pending')
        self.bot.delete_message.assert_not_awaited()

    async def test_pending_edit_blocks_manual_delete_as_well(self):
        await self.service.inspect(message(), self.bot, 1)
        self.service.latest_updates[(DISCUSSION, 20)] = 2
        await self.service.callback(self.query(), self.bot)
        self.assertEqual(self.state(), 'superseded')
        self.bot.delete_message.assert_not_awaited()

    async def test_failed_check_can_retry_same_content_on_new_update(self):
        self.classifier.side_effect = TimeoutError()
        await self.service.inspect(message(), self.bot, 1)
        self.classifier.side_effect = None
        await self.service.inspect(message(), self.bot, 2)
        self.assertEqual(self.state(), 'pending')
        self.assertEqual(self.classifier.await_count, 2)

    async def test_reconfigured_or_disabled_channel_cannot_delete_previous_comments(self):
        await self.service.inspect(message(), self.bot, 1)
        self.service.channel = ''
        await self.service.callback(self.query(), self.bot)
        self.service.channel = '@another_channel'
        self.bot.get_chat.side_effect = None
        self.bot.get_chat.return_value = NS(type='channel', linked_chat_id=None)
        await self.service.callback(self.query(), self.bot)
        self.bot.delete_message.assert_not_awaited()

    async def test_long_unicode_notification_fits_telegram_limits(self):
        await self.service.inspect(message(text='😀' * 4096), self.bot, 1)
        body = self.bot.send_message.call_args.args[1]
        self.assertLess(len(body.encode('utf-16-le')) // 2, 4096)

    async def test_dispatcher_routes_messages_and_edits_before_generic_handlers(self):
        with patch('bot.moderation.inspect', AsyncMock(return_value=True)) as inspect:
            await dp.feed_update(app_bot, Update(update_id=123, message=message()))
            self.assertEqual(inspect.call_args.args[2], 123)
            await dp.feed_update(app_bot, Update(update_id=124, edited_message=message()))
            self.assertEqual(inspect.call_args.args[2], 124)
        self.assertIn('edited_message', dp.resolve_used_update_types())
        with patch('bot.moderation.manual_check', AsyncMock()) as check, \
                patch('bot.moderation.inspect', AsyncMock(return_value=False)) as inspect:
            await dp.feed_update(app_bot, Update(update_id=125, message=self.forwarded(message())))
            check.assert_awaited_once()
            self.assertEqual(check.call_args.args[2], 125)
        with patch('bot._detect_availability_intent') as detect:
            await handle_group_message(message(text='Запустим опрос на октябрь'))
            detect.assert_not_called()


class ClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_output_and_no_tool_access(self):
        client = NS(chat=AsyncMock(return_value=NS(text='{"spam":true,"reason":"Реклама в имени"}')))
        payload = {'text': 'Привет', 'sender': {'name': 'Заработок', 'username': 'advert'}}
        with patch('modules.moderation.services.get_llm_client', return_value=client):
            self.assertEqual(await classify(payload), (True, 'Реклама в имени'))
            sent = client.chat.call_args
            self.assertEqual(json.loads(sent.args[0][1].text), payload)
            self.assertNotIn('tools', sent.kwargs)
            for raw in ('not JSON', '{"spam":"false","reason":"x"}', '[]', '{"spam":true}'):
                client.chat.return_value.text = raw
                with self.assertRaises(ValueError):
                    await classify(payload)
