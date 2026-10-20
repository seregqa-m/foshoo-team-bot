"""Conservative local spam checks. Links, criticism and profanity alone are allowed.

Rules combine several signals; they cannot understand quotations or sarcasm.
Start with MODERATION_AUTO_DELETE=false when tuning them for a new discussion.
"""
import re
import unicodedata


def pattern(value):
    return re.compile(value, re.IGNORECASE)


EARNINGS = pattern(r'\b(?:заработ(?:ок|ка|ать|аешь|аете)|доход\w*)\b')
EASY_MONEY = pattern(
    r'\bбез\s+(?:опыта|вложений)\b|\bпассивн\w*\s+доход\w*\b|'
    r'\b\d[\d\s.,]{0,12}\s*(?:₽|руб\w*\.?|р\.|\$)?\s*(?:в|за)\s+(?:день|час|сутки)\b'
)
CONTACT = pattern(
    r'\b(?:пиши(?:те)?|напиши(?:те)?)\s+(?:мне|в\s+(?:лс|личк\w*|личн\w*))\b|'
    r'\b(?:переходи(?:те)?|заходи(?:те)?)\s+(?:по\s+ссылке|в\s+(?:профиль|канал))\b|'
    r'\b(?:регистрируйся|регистрируйтесь)\b'
)
LINK = pattern(r'https?://|\bt\.me/|@[a-z0-9_]{5,32}\b')
CASINO = pattern(r'\b(?:казино|casino|слоты)\b')
BONUS = pattern(r'\b(?:бонус\w*|фриспин\w*|промокод\w*)\b')
INVESTMENT = pattern(r'\b(?:инвестиц\w*|крипт\w*|трейдинг\w*)\b')
GUARANTEE = pattern(r'\bгарантирован\w*\s+(?:доход\w*|прибыл\w*)\b|\bбез\s+риска\b')


def normalize(value):
    value = unicodedata.normalize('NFKC', str(value or '')[:20000])
    return ''.join(c for c in value if unicodedata.category(c) != 'Cf').lower().replace('ё', 'е')


async def classify(payload):
    sender = payload.get('sender') or {}
    fields = (
        ('тексте', normalize(payload.get('text'))),
        ('имени автора', normalize(sender.get('name'))),
        ('username автора', normalize(sender.get('username'))),
    )
    hidden_link = any(LINK.search(normalize(link)) for link in (payload.get('links') or [])[:100])
    for location, value in fields:
        contact = CONTACT.search(value)
        if EARNINGS.search(value) and EASY_MONEY.search(value) and contact:
            return True, f'Правило: предложение лёгкого заработка с призывом связаться в {location}.'
        linked = hidden_link or LINK.search(value)
        if CASINO.search(value) and BONUS.search(value) and contact and linked:
            return True, f'Правило: реклама казино с бонусом и приглашением по ссылке в {location}.'
        if INVESTMENT.search(value) and GUARANTEE.search(value) and contact:
            return True, f'Правило: предложение инвестиций с гарантией дохода и призывом связаться в {location}.'
    return False, 'Явных признаков спама по правилам не найдено.'
