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
        self.service = ModerationService('@example_channel', 42, -100300, self.Session)
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
        restarted = ModerationService('@example_channel', 42, -100300, self.Session)
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

    def forwarded(self, comment, sender_id=42, forward_from_chat=None, **kwargs):
        """Личка модератору: пересылка `comment` из группы обсуждений."""
        return Message(
            message_id=1000, date=datetime.now(timezone.utc),
            chat=Chat(id=42, type='private'),
            from_user=User(id=sender_id, is_bot=False, first_name='Moderator'),
            forward_from_chat=forward_from_chat or Chat(id=DISCUSSION, type='supergroup'),
            forward_from_message_id=comment.message_id,
            forward_from=comment.from_user,
            forward_date=comment.date,
            text=comment.text, caption=comment.caption,
            entities=comment.entities, caption_entities=comment.caption_entities,
            **kwargs,
        )

    async def test_manual_check_existing_comment_then_delete_exact_original(self):
        comment = message(date=datetime.now(timezone.utc) - timedelta(hours=2))
        await self.service.manual_check(self.forwarded(comment), self.bot, 1)
        self.assertEqual(self.state(), 'pending')
        self.bot.delete_message.assert_not_awaited()
        await self.service.callback(self.query(), self.bot)
        self.bot.delete_message.assert_awaited_once_with(DISCUSSION, 20)

    async def test_manual_check_sends_review_buttons_even_on_false_negative(self):
        self.classifier.return_value = (False, 'Нейтральный текст')
        await self.service.manual_check(self.forwarded(message()), self.bot, 1)
        self.assertEqual(self.state(), 'pending')
        self.assertIn('ИИ не обнаружил', self.bot.send_message.call_args.args[1])
        self.assertIsNotNone(self.bot.send_message.call_args.kwargs['reply_markup'])
        self.bot.delete_message.assert_not_awaited()

    async def test_manual_check_forward_from_hidden_profile_still_works(self):
        # Автор оригинального комментария скрыл пересылки: forward_from недоступен,
        # есть только forward_sender_name. Классификатору всё равно уходит имя.
        comment = message()
        forward = Message(
            message_id=1000, date=datetime.now(timezone.utc),
            chat=Chat(id=42, type='private'),
            from_user=User(id=42, is_bot=False, first_name='Moderator'),
            forward_from_chat=Chat(id=DISCUSSION, type='supergroup'),
            forward_from_message_id=comment.message_id,
            forward_sender_name='Скрытый Автор',
            forward_date=comment.date,
            text=comment.text,
        )
        await self.service.manual_check(forward, self.bot, 1)
        self.assertEqual(self.state(), 'pending')
        payload = self.classifier.call_args.args[0]
        self.assertEqual(payload['sender'], {'name': 'Скрытый Автор', 'username': '', 'kind': 'user'})
        with self.Session() as db:
            self.assertIsNone(db.query(ModerationComment).one().author_id)

    async def test_manual_request_rejects_non_recipient_non_forward_and_other_sources(self):
        # Обычное сообщение без forward — фильтр F.forward_date не пропустит, но проверим и на уровне сервиса.
        plain = Message(message_id=1, date=datetime.now(timezone.utc),
                        chat=Chat(id=42, type='private'),
                        from_user=User(id=42, is_bot=False, first_name='Mod'), text='hi')
        await self.service.manual_check(plain, self.bot, 1)
        # Forward от постороннего пользователя игнорируется.
        await self.service.manual_check(self.forwarded(message(), sender_id=84), self.bot, 2)
        # Forward из другого чата отклоняется.
        await self.service.manual_check(self.forwarded(message(), forward_from_chat=Chat(
            id=-100999, type='supergroup')), self.bot, 3)
        # Пересылка поста самого канала (source == target[0]) отклоняется.
        await self.service.manual_check(self.forwarded(message(), forward_from_chat=Chat(
            id=CHANNEL, type='channel', title='Наш канал')), self.bot, 4)
        # Пересылка без текста и подписи отклоняется.
        await self.service.manual_check(self.forwarded(message(text=None)), self.bot, 5)
        self.classifier.assert_not_awaited()
        self.bot.delete_message.assert_not_awaited()

    async def test_manual_recheck_cannot_retry_unknown_deletion(self):
        await self.service.inspect(message(), self.bot, 1)
        self.bot.delete_message.side_effect = TimeoutError()
        await self.service.callback(self.query(), self.bot)
        await self.service.manual_check(self.forwarded(message()), self.bot, 2)
        self.assertEqual(self.state(), 'delete_unknown')
        self.classifier.assert_awaited_once()
        self.bot.delete_message.assert_awaited_once()

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
