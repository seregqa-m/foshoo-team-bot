"""Shared subscriptions generated once per real combination of Sheets casts."""
import hashlib
import json
import os
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, MINI_APP_URL
from core.database import get_db
from core.time import local_now
from sheets_client import SheetsClient
from modules.theater.models import TheaterShow
from modules.theater.routing import show_aliases, match_show, saved_event_show
from modules.theater.services import normalize_name
from .classification import classify_event
from .models import CalendarEvent, CalendarSubscription
from .ical import render_calendar

public_router = APIRouter(tags=['calendar-feed'])


def read_roster():
    try:
        if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
            raise ValueError('Sheets not configured')
        return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, timeout=15).get_attendance_roster()
    except Exception:
        raise HTTPException(503, 'Не удалось прочитать составы. Ссылки не изменены.') from None


def combination_plan(db, source):
    """Only actual actor→show sets, never the mathematical power set.

    Names group rows inside Sheets only. No Telegram identity or participant
    names are returned, saved in subscriptions or exposed by the public feed.
    """
    aliases = show_aliases(db)
    actors = defaultdict(set)
    unresolved = set()
    for row in source['casts'][1:]:
        if not row or not any(str(cell).strip() for cell in row):
            continue
        if len(row) < 3 or not str(row[0]).strip() or not str(row[2]).strip():
            raise HTTPException(409, 'В «Составах спектаклей» есть неполная строка: нужны спектакль и участник.')
        show = aliases.get(normalize_name(str(row[0])))
        if not show:
            unresolved.add(str(row[0]).strip())
        else:
            actors[normalize_name(str(row[2]))].add(show.id)
    if unresolved:
        raise HTTPException(409, 'Свяжите названия составов с каталогом или псевдонимами: ' + ', '.join(sorted(unresolved)))
    names = Counter(normalize_name(str(row[0])) for row in source.get('troupe', [])[1:] if row and str(row[0]).strip())
    if any(names[actor] > 1 for actor in actors):
        raise HTTPException(409, 'В «Труппе» повторяются имена участников составов. Уточните имена, чтобы не объединить разных людей.')
    shows = {show.id: show.name for show in aliases.values()}
    return plan_for_sets(actors.values(), shows)


def plan_for_sets(selections, shows):
    groups = []
    for ids in sorted({tuple(sorted(set(ids))) for ids in selections}):
        titles = sorted(shows[ident] for ident in ids)
        key = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        groups.append({'scope_key': 'casts:' + key, 'show_ids': list(ids), 'shows': titles,
                       'name': 'FoShoo — ' + ' + '.join(titles)})
    groups.sort(key=lambda item: item['name'])
    if not groups:
        raise HTTPException(409, 'В таблице не найдено ни одного состава. Ссылки не изменены.')
    fingerprint = hashlib.sha256(json.dumps(groups, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'groups': groups, 'fingerprint': fingerprint}


def selected_plan(db, show_names=None):
    if show_names is None:
        return combination_plan(db, read_roster())
    if not isinstance(show_names, list) or not show_names or len(show_names) > 100 or any(
            not isinstance(name, str) or not name.strip() for name in show_names):
        raise HTTPException(422, 'Укажите непустой список названий спектаклей.')
    aliases = show_aliases(db)
    shows = {}
    for name in show_names:
        show = match_show(name, aliases, exact=True)
        if show is None:
            raise HTTPException(409, f'Спектакль «{name}» не найден. Укажите точное название или псевдоним из каталога.')
        shows[show.id] = show.name
    return {**plan_for_sets([shows.keys()], shows), 'show_names': sorted(shows.values())}


def public_base_url(value=MINI_APP_URL):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(503, 'Для календарных ссылок нужен публичный HTTPS-адрес MINI_APP_URL')
    if parsed.hostname in ('localhost', '127.0.0.1', 'your-tunnel.trycloudflare.com') or parsed.hostname == 't.me':
        raise HTTPException(503, 'MINI_APP_URL должен указывать на публичный сайт приложения')
    return f'{parsed.scheme}://{parsed.netloc}'


def link_data(row, base_url):
    url = f'{base_url}/api/calendar/feeds/{row.token}.ics' if not row.revoked_at else None
    return {'id': row.id, 'name': row.name, 'show_ids': row.show_ids, 'url': url,
            'webcal_url': url.replace('https:', 'webcal:', 1) if url else None,
            'revoked': row.revoked_at is not None}


def prepare_links(db, show_names=None):
    public_base_url()  # Fail before asking to confirm a deployment misconfiguration.
    return selected_plan(db, show_names)


def rebuild_links(db, expected_fingerprint, *, show_names=None, base_url=None):
    base_url = public_base_url(base_url) if base_url else public_base_url()
    plan = selected_plan(db, show_names)
    if plan['fingerprint'] != expected_fingerprint:
        raise HTTPException(409, 'Составы или каталог изменились. Запросите пересборку заново и проверьте новые комбинации.')
    rows = []
    for group in plan['groups']:
        row = db.query(CalendarSubscription).filter_by(scope_key=group['scope_key']).first()
        if row is None:
            try:
                with db.begin_nested():
                    row = CalendarSubscription(scope_key=group['scope_key'], name=group['name'],
                                               show_ids=group['show_ids'], token=secrets.token_urlsafe(32))
                    db.add(row)
                    db.flush()
            except IntegrityError:
                row = db.query(CalendarSubscription).filter_by(scope_key=group['scope_key']).first()
                if row is None:
                    raise
        # Never rotate tokens, widen a saved selection or revive a revoked URL.
        row.name = group['name']
        rows.append(row)
    db.commit()
    links = [link_data(row, base_url) for row in rows]
    return {'calendar_links': links, 'count': len(links),
            'note': 'Это общие подписки без входа. Старые ссылки сохранены; новые комбинации добавлены. Ничего в чаты не отправлено.'}


def revoke_link(db, subscription_id):
    row = db.get(CalendarSubscription, subscription_id)
    if not row:
        raise HTTPException(404, 'Подписка не найдена')
    row.revoked_at = datetime.utcnow()
    db.commit()


def build_feed(db, row):
    ids = set(row.show_ids)
    current = {ident for ident, in db.query(TheaterShow.id).filter(TheaterShow.id.in_(ids))}
    if current != ids:
        raise HTTPException(503, 'Спектакль подписки отсутствует в каталоге')
    aliases = show_aliases(db)
    now = local_now()
    events = db.query(CalendarEvent).filter(
        # This URL is a complete schedule snapshot, not cancellation messages.
        # Publishing old tombstones can make clients display deleted repeats.
        CalendarEvent.is_cancelled == False,
        CalendarEvent.end_time >= now - timedelta(days=30),
        CalendarEvent.start_time <= now + timedelta(days=90),
    ).order_by(CalendarEvent.start_time, CalendarEvent.id).all()
    selected = []
    for event in events:
        if classify_event(event.title, aliases)['event_type'] not in ('rehearsal', 'performance'):
            continue
        show = saved_event_show(db, event) or match_show(event.title, aliases)
        if show and show.id in ids:
            selected.append(event)
    return render_calendar(selected, row.name)


@public_router.api_route('/api/calendar/feeds/{token}.ics', methods=['GET', 'HEAD'])
def calendar_feed(token: str, request: Request, db: Session = Depends(get_db)):
    if len(token) != 43:
        raise HTTPException(404, 'Подписка не найдена')
    row = db.query(CalendarSubscription).filter_by(token=token, revoked_at=None).first()
    if not row:
        raise HTTPException(404, 'Подписка не найдена')
    body = build_feed(db, row)
    return Response('' if request.method == 'HEAD' else body, media_type='text/calendar',
                    headers={'Cache-Control': 'private, no-store', 'X-Robots-Tag': 'noindex, nofollow',
                             'Content-Length': str(len(body.encode())),
                             'Content-Disposition': 'inline; filename="foshoo.ics"'})
