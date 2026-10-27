"""One discussion group, one reviewer. Automatic spam removal with durable deletion outcomes."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import logging
import re
import time

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from core.database import SessionLocal
from .classifier import Verdict, classify, fingerprint
from .models import ModerationComment, ModerationDecision, ModerationReviewItem

logger = logging.getLogger(__name__)


def excerpt(value, units):
    """Telegram limits text by UTF-16 units, including emoji in spam."""
    encoded = value.encode('utf-16-le')
    return value if len(encoded) <= units * 2 else encoded[:(units - 1) * 2].decode('utf-16-le', errors='ignore') + '…'


class ModerationService:
    def __init__(self, channel='', recipient_id=0, internal_chat_id=0, session_factory=SessionLocal, auto_delete=True):
        self.auto_delete = auto_delete
        self.latest_updates = {}
        self.channel = channel
        self.recipient_id = recipient_id
        self.internal_chat_id = internal_chat_id
        self.session_factory = session_factory
        self.lock = asyncio.Lock()
        self.resolve_lock = asyncio.Lock()
        self.target = None
        self.expires = 0
        self.status = 'Модерация выключена: задайте MODERATION_CHANNEL.'

    async def resolve(self, bot, force=False):
        if not self.channel or self.recipient_id <= 0:
            self.status = 'Модерация выключена: нужны MODERATION_CHANNEL и положительный MODERATION_ADMIN_ID (или ADMIN_ID).'
            return None
        async with self.resolve_lock:
            if not force and time.monotonic() < self.expires:
                return self.target
            self.target = None
            self.expires = time.monotonic() + 60
            try:
                if not re.fullmatch(r'@[A-Za-z0-9_]{5,32}|-100\d+', self.channel):
                    raise ValueError('MODERATION_CHANNEL: укажите @username или числовой ID канала, без t.me/.')
                channel = await bot.get_chat(int(self.channel) if self.channel.startswith('-') else self.channel)
                if channel.type != 'channel' or not channel.linked_chat_id:
                    raise ValueError('У канала нет привязанной группы обсуждений.')
                discussion = await bot.get_chat(channel.linked_chat_id)
                if discussion.type != 'supergroup' or discussion.linked_chat_id != channel.id:
                    raise ValueError('Не подтверждена связь канала с группой обсуждений.')
                if discussion.id == self.internal_chat_id:
                    raise ValueError('Группа обсуждений совпадает с внутренним GROUP_CHAT_ID. Для публичных комментариев нужна отдельная группа.')
                member = await bot.get_chat_member(discussion.id, bot.id)
                if member.status != 'administrator' or not member.can_delete_messages:
                    raise ValueError('Выдайте боту права администратора с удалением сообщений в группе обсуждений.')
                self.target = (channel.id, discussion.id)
                self.expires = time.monotonic() + 300
                self.status = ('ИИ-модерация подключена. Спам удаляется автоматически; сомнения — на проверку. Кеш — 24 часа.'
                               if self.auto_delete else
                               'ИИ-модерация подключена. Уведомления — в личку; удаление — только по кнопке.')
            except ValueError as exc:
                self.status = str(exc)
            except Exception as exc:
                self.status = f'Не удалось проверить подключение Telegram ({type(exc).__name__}). Проверьте канал и права бота.'
            if not self.target:
                logger.warning('Moderation: %s', self.status)
            return self.target

    @staticmethod
    def notification(row, status='Комментарий оставлен без изменений.'):
        return (f'🔎 Проверка комментария\nАвтор: {excerpt(row.author, 200)}\n\n'
                f'{excerpt(row.text, 2400)}\n\nПричина: {excerpt(row.reason, 450)}\n\n{status}')

    @staticmethod
    def keyboard(row):
        # c/ links also work when the discussion group has no public username.
        link = f'https://t.me/c/{str(row.chat_id)[4:]}/{row.message_id}'
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Открыть комментарий', url=link)],
            [InlineKeyboardButton(text='🗑 Это спам — удалить', callback_data=f'mod:spam:{row.id}:{row.revision}')],
            [InlineKeyboardButton(text='✅ Это не спам', callback_data=f'mod:keep:{row.id}:{row.revision}')],
        ])

    async def inspect(self, message, bot, update_id):
        if (not self.channel or message.chat.type not in ('group', 'supergroup') or
                message.chat.id == self.internal_chat_id):
            return False
        target = await self.resolve(bot)
        if not target or message.chat.id != target[1]:
            return False
        # Do not moderate channel posts, anonymous chat admins or our own messages.
        if (message.is_automatic_forward or
                (message.sender_chat and message.sender_chat.id in target) or
                (message.from_user and message.from_user.id == bot.id)):
            return True
        key = (message.chat.id, message.message_id)
        logger.info('Moderation received message=%s update=%s', message.message_id, update_id)
        self.latest_updates[key] = max(update_id, self.latest_updates.get(key, update_id))
        try:
            async with self.lock:
                try:
                    await self._inspect(message, bot, update_id, target)
                except Exception as exc:
                    logger.warning('Moderation check failed (%s) message=%s update=%s',
                                   type(exc).__name__, message.message_id, update_id)
        finally:
            if self.latest_updates.get(key) == update_id:
                self.latest_updates.pop(key, None)
        return True  # Never let public comments trigger internal bot commands.

    async def manual_check(self, forwarded, bot, update_id):
        # User/hidden-user forwards contain no original chat/message ID. Never
        # infer a deletion target from their text, author or timestamp.
        if (not forwarded.from_user or forwarded.from_user.id != self.recipient_id or
                forwarded.chat.type != 'private' or forwarded.sender_chat):
            return
        if not await self.resolve(bot):
            await bot.send_message(self.recipient_id, self.status)
            return
        origin = forwarded.forward_origin
        if not origin or origin.type not in ('user', 'hidden_user'):
            await bot.send_message(self.recipient_id, 'Перешлите текстовый комментарий пользователя. Посты каналов не проверяются.')
            return
        fields = self._extract_from_live(forwarded)
        if not fields['text'].strip():
            await bot.send_message(self.recipient_id, 'Нужен текстовый комментарий или подпись, а не медиа без текста.')
            return
        author = origin.sender_user if origin.type == 'user' else None
        payload = {'text': fields['text'], 'links': fields['links'], 'sender': {
            'name': author.full_name if author else origin.sender_user_name,
            'username': (author.username or '') if author else '', 'kind': 'user',
        }}
        try:
            verdict = await classify(payload)
            result = {'spam': 'Обнаружен спам.', 'allow': 'Спам не обнаружен.',
                      'review': 'Модель сомневается: нужна ваша проверка.'}[verdict.verdict]
            text = (f'🔎 Проверка пересланного текста\n{result}\n{verdict.reason}\n\n'
                    'Telegram не передал ID исходной группы и комментария. '
                    'Источник не подтверждён; удаление возможно только вручную в Telegram.')
        except Exception as exc:
            logger.warning('Forward moderation check failed (%s)', type(exc).__name__)
            text = 'Не удалось проверить пересланный текст. Проверьте комментарий вручную.'
        await bot.send_message(self.recipient_id, text, parse_mode=None)

    @staticmethod
    def _extract_from_live(message):
        text = message.text or message.caption or ''
        entities = message.entities or message.caption_entities or []
        links = [e.url for e in entities if e.type == 'text_link' and e.url]
        if message.sender_chat:
            sender_name = message.sender_chat.title or ''
            username = message.sender_chat.username or ''
            kind = 'channel'
            author_id = None
        else:
            sender_name = message.from_user.full_name if message.from_user else 'Неизвестный автор'
            username = (message.from_user.username or '') if message.from_user else ''
            kind = 'user'
            author_id = message.from_user.id if message.from_user else None
        return {
            'chat_id': message.chat.id, 'message_id': message.message_id,
            'message_time': int(message.date.timestamp()),
            'text': text, 'links': links,
            'sender_name': sender_name, 'username': username, 'kind': kind,
            'author_id': author_id,
        }

    async def _inspect(self, message, bot, update_id, target):
        await self._inspect_extracted(self._extract_from_live(message), bot, update_id, target)

    async def _inspect_extracted(self, fields, bot, update_id, target):
        payload = {'text': fields['text'], 'links': fields['links'], 'sender': {
            'name': fields['sender_name'], 'username': fields['username'], 'kind': fields['kind'],
        }}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.session_factory() as db:
            row = db.query(ModerationComment).filter_by(chat_id=fields['chat_id'], message_id=fields['message_id']).first()
            if row and update_id <= row.last_update_id:
                return
            if row and row.state in ('deleted', 'deleting', 'delete_unknown'):
                return
            if (row and row.content_hash == digest
                    and row.state not in ('check_failed', 'notification_failed', 'checking', 'superseded')):
                row.last_update_id = update_id
                db.commit()
                return
            if not row:
                if not fields['text'].strip():
                    return
                row = ModerationComment(channel_id=target[0], chat_id=fields['chat_id'], message_id=fields['message_id'],
                                        recipient_id=self.recipient_id, revision=0)
                db.add(row)
            # Invalidate any old buttons before checking a changed comment.
            row.revision += 1
            row.last_update_id = update_id
            row.content_hash = digest
            row.text = fields['text']
            row.state = 'checking'
            row.notification_id = None
            row.recipient_id = self.recipient_id
            row.channel_id = target[0]
            row.message_time = fields['message_time']
            row.updated_at = datetime.utcnow()
            row.author_id = fields['author_id']
            row.author = (f"{fields['sender_name']} (@{fields['username']})"
                          if fields['username'] else fields['sender_name'])
            db.commit()
            try:
                if row.author_id:
                    author = await bot.get_chat_member(target[1], row.author_id)
                    if author.status in ('administrator', 'creator'):
                        row.state = 'exempt'
                        db.commit()
                        return
                if not fields['text'].strip():
                    row.state = 'clear'
                    db.commit()
                    return
                now = datetime.utcnow()
                key = fingerprint(payload)
                decision = db.query(ModerationDecision).filter(
                    ModerationDecision.channel_id == row.channel_id,
                    ModerationDecision.chat_id == row.chat_id,
                    ModerationDecision.recipient_id == self.recipient_id,
                    ModerationDecision.fingerprint == key,
                    ModerationDecision.expires_at > now,
                ).order_by(ModerationDecision.id.desc()).first()
                if decision:
                    verdict = Verdict(decision.verdict, decision.reason)
                else:
                    try:
                        verdict = await classify(payload)
                    except Exception as exc:
                        logger.warning('Moderation model failed (%s) message=%s', type(exc).__name__, row.message_id)
                        verdict = Verdict('review', f'Модель не смогла проверить комментарий ({type(exc).__name__}). Нужна ваша проверка.')
                if self.latest_updates.get((row.chat_id, row.message_id), update_id) != update_id:
                    row.state = 'superseded'
                    db.commit()
                    return
                review = verdict.verdict == 'review' or (verdict.verdict == 'spam' and not self.auto_delete)
                if review and decision and decision.verdict != 'review':
                    # A change to manual mode must not revive an old card's buttons.
                    decision = None
                if not decision and verdict.verdict != 'allow':
                    decision = ModerationDecision(channel_id=row.channel_id, chat_id=row.chat_id,
                        recipient_id=self.recipient_id, fingerprint=key,
                        verdict='review' if review else verdict.verdict, reason=verdict.reason,
                        expires_at=datetime.utcnow() + timedelta(hours=24))
                    db.add(decision)
                row.reason = verdict.reason
                spam = verdict.verdict == 'spam'
                row.state = 'pending' if review or spam else 'clear'
                db.commit()
                logger.info('Moderation verdict message=%s update=%s spam=%s state=%s',
                            row.message_id, update_id, spam, row.state)
                if review:
                    await self._queue_review(bot, row, decision, db)
                    return
            except Exception as exc:
                row.state = 'notification_failed' if row.state == 'notifying' else 'check_failed'
                db.commit()
                await self._alert_check_failed(bot, row, type(exc).__name__)
                raise
            if spam and self.auto_delete:
                result = await self._delete_comment(bot, row, db)
                try:
                    sent = await bot.send_message(self.recipient_id, self.notification(row, result),
                                                  reply_markup=self.keyboard(row) if row.state == 'pending' else None,
                                                  parse_mode=None, disable_web_page_preview=True)
                    row.notification_id = sent.message_id
                    db.commit()
                except Exception as exc:
                    logger.warning('Moderation result delivery failed (%s); saved state=%s', type(exc).__name__, row.state)

    @staticmethod
    def _review_keyboard(decision):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🗑 Спам — удалить все', callback_data=f'mod:batch:spam:{decision.id}')],
            [InlineKeyboardButton(text='✅ Не спам — оставить все', callback_data=f'mod:batch:keep:{decision.id}')],
        ])

    @staticmethod
    def _review_rows(db, decision):
        return db.query(ModerationComment).join(
            ModerationReviewItem, ModerationReviewItem.comment_id == ModerationComment.id,
        ).filter(
            ModerationReviewItem.decision_id == decision.id,
            ModerationReviewItem.revision == ModerationComment.revision,
            ModerationComment.channel_id == decision.channel_id,
            ModerationComment.chat_id == decision.chat_id,
            ModerationComment.recipient_id == decision.recipient_id,
            ModerationComment.state.in_(('pending', 'notifying', 'notification_failed')),
        ).order_by(ModerationComment.id).all()

    async def _queue_review(self, bot, row, decision, db):
        item = db.get(ModerationReviewItem, (decision.id, row.id))
        if item:
            item.revision = row.revision
        else:
            db.add(ModerationReviewItem(decision_id=decision.id, comment_id=row.id, revision=row.revision))
        row.state = 'pending'
        db.commit()
        count = len(self._review_rows(db, decision))
        link = f'https://t.me/c/{str(row.chat_id)[4:]}/{row.message_id}'
        body = (f'🔎 Нужна ваша проверка\nСообщений в группе: {count}\n'
                f'Пример от: {excerpt(row.author, 200)}\n{link}\n\n'
                f'{excerpt(row.text, 2400)}\n\nПричина: {excerpt(decision.reason, 450)}\n\n'
                'Кнопка применится ко всем неизменённым сообщениям этой группы. '
                'Одинаковые комментарии за 24 часа объединяются здесь.')
        keyboard = self._review_keyboard(decision)
        if decision.notification_id is None:
            # A lost send response must not create many independent cards.
            decision.notification_id = -1
            row.state = 'notifying'
            db.commit()
            try:
                sent = await bot.send_message(self.recipient_id, body, reply_markup=keyboard,
                                              parse_mode=None, disable_web_page_preview=True)
            except TelegramBadRequest:
                decision.notification_id = None  # Telegram definitively rejected the send.
                db.commit()
                raise
            decision.notification_id = sent.message_id
        elif decision.notification_id > 0:
            try:
                await bot.edit_message_text(chat_id=self.recipient_id, message_id=decision.notification_id,
                                            text=body, reply_markup=keyboard, parse_mode=None,
                                            disable_web_page_preview=True)
            except Exception as exc:
                # The old card still approves all current members of the batch.
                logger.warning('Moderation review count update failed (%s)', type(exc).__name__)
        row.notification_id = decision.notification_id if decision.notification_id > 0 else None
        row.state = 'pending'
        db.commit()

    async def _batch_callback(self, query, bot):
        match = re.fullmatch(r'mod:batch:(spam|keep):(\d+)', query.data or '')
        if (not match or query.from_user.id != self.recipient_id or not query.message
                or query.message.chat.type != 'private' or query.message.chat.id != self.recipient_id):
            await query.answer('Действие недоступно.', show_alert=True)
            return
        await query.answer('Обрабатываю…')
        action, decision_id = match.groups()
        async with self.lock:
            with self.session_factory() as db:
                decision = db.get(ModerationDecision, int(decision_id))
                if (not self.channel or not decision or decision.recipient_id != self.recipient_id
                        or decision.notification_id != query.message.message_id or decision.verdict != 'review'):
                    return
                if await self.resolve(bot, force=True) != (decision.channel_id, decision.chat_id):
                    await bot.send_message(self.recipient_id, 'Не удалось подтвердить канал и права бота. Повторите позже.')
                    return
                rows = [row for row in self._review_rows(db, decision)
                        if self.latest_updates.get((row.chat_id, row.message_id), row.last_update_id) <= row.last_update_id]
                if not rows:
                    await bot.send_message(self.recipient_id, 'В этой группе нет неизменённых комментариев для обработки.')
                    return
                deleted = 0
                for row in rows:
                    if action == 'keep':
                        row.state = 'not_spam'
                    else:
                        await self._delete_comment(bot, row, db)
                        deleted += row.state == 'deleted'
                    row.updated_at = datetime.utcnow()
                    db.commit()
                pending = any(row.state == 'pending' for row in rows)
                decision.verdict = 'review' if pending else ('spam' if action == 'spam' else 'allow')
                decision.reason = 'Модератор подтвердил спам.' if action == 'spam' else 'Модератор подтвердил: не спам.'
                decision.expires_at = datetime.utcnow() + timedelta(hours=24)
                db.commit()
                result = (f'🗑 Удалено: {deleted} из {len(rows)}. Остальные оставлены или удаление не подтверждено.'
                          if action == 'spam' else f'✅ Не спам. Оставлено сообщений: {len(rows)}.')
                if pending:
                    result += '\nУдаление части сообщений отклонено или права не подтверждены. Можно повторить проверку кнопкой.'
                else:
                    result += '\nРешение сохранено на 24 часа.'
                try:
                    await bot.edit_message_text(chat_id=self.recipient_id, message_id=decision.notification_id,
                        text=result, parse_mode=None,
                        reply_markup=self._review_keyboard(decision) if pending else None)
                except Exception as exc:
                    logger.warning('Moderation batch result delivery failed (%s)', type(exc).__name__)

    async def _alert_check_failed(self, bot, row, exc_type):
        # Notification path is already broken when we hit notification_failed,
        # but attempt anyway — the send limit may be per-payload, not global.
        link = f'https://t.me/c/{str(row.chat_id)[4:]}/{row.message_id}'
        text = (f'⚠️ Не смогла проверить комментарий (ошибка: {exc_type}).\n'
                f'Автор: {excerpt(row.author, 200)}\n\n'
                f'{excerpt(row.text, 2400)}\n\nПроверь вручную.')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='Открыть комментарий', url=link),
        ]])
        try:
            await bot.send_message(self.recipient_id, text, reply_markup=keyboard,
                                   parse_mode=None, disable_web_page_preview=True)
        except Exception as alert_exc:
            logger.warning('Moderation alert send failed (%s)', type(alert_exc).__name__)

    async def callback(self, query, bot):
        if (query.data or '').startswith('mod:batch:'):
            return await self._batch_callback(query, bot)
        match = re.fullmatch(r'mod:(spam|keep):(\d+):(\d+)', query.data or '')
        if (not match or query.from_user.id != self.recipient_id or not query.message or
                query.message.chat.type != 'private' or query.message.chat.id != self.recipient_id):
            await query.answer('Действие недоступно.', show_alert=True)
            return
        action, row_id, revision = match.groups()
        await query.answer('Обрабатываю…')
        async with self.lock:
            with self.session_factory() as db:
                row = db.get(ModerationComment, int(row_id))
                if (not self.channel or not row or row.recipient_id != self.recipient_id or
                        row.notification_id != query.message.message_id or row.revision != int(revision)):
                    await bot.send_message(self.recipient_id, 'Уведомление устарело или модерация выключена.')
                    return
                if row.state != 'pending':
                    await bot.send_message(self.recipient_id, 'Уже обработано. При неопределённом результате проверьте комментарий вручную.')
                    return
                target = await self.resolve(bot, force=True)
                if target != (row.channel_id, row.chat_id):
                    await self._finish_notice(bot, row, 'Не удалось подтвердить канал и права бота. Повторите позже.', keep_buttons=True)
                    return
                result = '✅ Отмечено как «не спам». Комментарий оставлен.'
                if action == 'keep':
                    row.state = 'not_spam'
                else:
                    result = await self._delete_comment(bot, row, db)
                row.updated_at = datetime.utcnow()
                db.commit()
                await self._finish_notice(bot, row, result, keep_buttons=row.state == 'pending')

    async def _delete_comment(self, bot, row, db):
        target = await self.resolve(bot, force=True)
        if target != (row.channel_id, row.chat_id):
            return 'Не удалось подтвердить канал и права бота. Комментарий оставлен.'
        if time.time() - row.message_time >= 48 * 3600:
            row.state = 'expired'
            result = 'Telegram не позволяет боту удалить сообщение старше 48 часов. Удалите вручную.'
        else:
            if row.author_id:
                try:
                    member = await bot.get_chat_member(row.chat_id, row.author_id)
                except Exception:
                    return 'Не удалось проверить автора. Комментарий оставлен.'
                if member.status in ('creator', 'administrator'):
                    row.state = 'exempt'
                    db.commit()
                    return 'Комментарий администратора оставлен.'
            if self.latest_updates.get((row.chat_id, row.message_id), row.last_update_id) > row.last_update_id:
                row.state = 'superseded'
                db.commit()
                return 'Во время проверки комментарий изменился; ожидается новая проверка.'
            row.state = 'deleting'
            db.commit()  # Persist before the API call: never retry uncertain deletion.
            try:
                await bot.delete_message(row.chat_id, row.message_id)
                row.state = 'deleted'
                result = '🗑 Спам удалён. Автор не заблокирован.'
            except TelegramBadRequest as exc:
                if 'message to delete not found' in exc.message.lower():
                    row.state = 'deleted'
                    result = 'Комментарий уже отсутствует в Telegram.'
                else:
                    row.state = 'pending'
                    result = 'Telegram отклонил удаление. Проверьте права бота или удалите вручную.'
            except Exception as exc:
                logger.warning('Moderation delete uncertain (%s)', type(exc).__name__)
                row.state = 'delete_unknown'
                result = 'Не удалось подтвердить удаление. Проверьте комментарий вручную; повторное удаление заблокировано.'
        row.updated_at = datetime.utcnow()
        db.commit()
        return result

    async def _finish_notice(self, bot, row, result, keep_buttons=False):
        try:
            await bot.edit_message_text(chat_id=row.recipient_id, message_id=row.notification_id,
                                        text=self.notification(row, result), parse_mode=None,
                                        disable_web_page_preview=True,
                                        reply_markup=self.keyboard(row) if keep_buttons else None)
        except Exception as exc:
            logger.warning('Moderation notice update failed (%s); saved state=%s', type(exc).__name__, row.state)
