"""Destinations come only from the superadmin's show–chat table."""
import re
from fastapi import HTTPException
from modules.calendar.classification import SHOW_ALIASES
from .models import TheaterShow, TheaterShowAlias
from .services import normalize_name


def show_aliases(db):
    shows = {s.id: s for s in db.query(TheaterShow).all()}
    aliases = {normalize_name(s.name): s for s in shows.values()}
    aliases.update({a.normalized_name: shows[a.show_id] for a in db.query(TheaterShowAlias).all() if a.show_id in shows})
    for short, full in SHOW_ALIASES.items():
        if normalize_name(full) in aliases:
            aliases[normalize_name(short)] = aliases[normalize_name(full)]
    return aliases


def resolve_show(db, title, *, exact=False):
    aliases = show_aliases(db)
    key = normalize_name(title)
    if key in aliases:
        return aliases[key]
    if not exact:
        key = re.sub(r'\[[^\[\]]*\]', ' ', key)
        matches = {s.id: s for alias, s in aliases.items()
                   if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', key)}
        if len(matches) == 1:
            return next(iter(matches.values()))
    raise HTTPException(409, f'Укажите спектакль из «Спектакли и чаты» в названии события: {title}')


def event_destination(db, event):
    show = resolve_show(db, event.title)
    if not show.telegram_chat_id:
        raise HTTPException(409, f'Для «{show.name}» не указан ID чата в настройках')
    return show


def campaign_destinations(db, names):
    destinations = {}
    for name in names:
        show = resolve_show(db, name, exact=True)
        if not show.telegram_chat_id:
            raise HTTPException(409, f'Для «{show.name}» не указан ID чата в настройках')
        destinations.setdefault(show.telegram_chat_id, set()).add(show.name)
    return {chat: sorted(shows) for chat, shows in destinations.items()}


def sheet_show_names(db, name):
    """Include earlier imported spellings after renaming a show in the app."""
    show = resolve_show(db, name, exact=True)
    return {normalize_name(show.name)} | {a.normalized_name for a in db.query(TheaterShowAlias).filter_by(show_id=show.id)}


def cast_usernames(db, names, client):
    from .services import normalize_name
    keys = set()
    for name in names:
        keys.update(sheet_show_names(db, name))
    source = client.get_planning_data()
    cast = {normalize_name(row[2]) for row in source['casts'][1:]
            if len(row) >= 3 and normalize_name(row[0]) in keys and row[2].strip()}
    return {username.lower() for username, actor in client.get_actor_mapping().items() if normalize_name(actor) in cast}


def poll_link(chat_id, message_id):
    if not chat_id or not message_id or not str(chat_id).startswith('-100'):
        return None
    return f'https://t.me/c/{str(chat_id)[4:]}/{message_id}'
