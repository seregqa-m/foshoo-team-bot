"""Expose cast members missing from the verified Telegram roster; never ping them."""
import json
from collections import Counter, defaultdict

from modules.attendance.models import ChatParticipant, VoterRegistration
from modules.attendance.roster import answered_dates
from modules.attendance.services import option_day
from modules.theater.routing import campaign_destinations, sheet_show_names
from modules.theater.services import normalize_name


def cast_identities(db, campaign, source):
    """Resolve Sheets casts to known IDs without inferring identity from names."""
    destinations = campaign_destinations(db, json.loads(campaign.show_names))
    show_keys = {}
    for chat, shows in destinations.items():
        for show in shows:
            for key in sheet_show_names(db, show):
                show_keys[key] = (chat, show)
    expected = {}
    for row in source['casts'][1:]:
        if len(row) < 3 or not row[2].strip() or normalize_name(row[0]) not in show_keys:
            continue
        chat, show = show_keys[normalize_name(row[0])]
        actor = expected.setdefault(normalize_name(row[2]), {'name': row[2].strip(), 'shows': set(), 'chats': set()})
        actor['shows'].add(show)
        actor['chats'].add(chat)

    troupe = source['troupe']
    headers = troupe[0] if troupe else []
    id_columns = [i for i, value in enumerate(headers) if str(value).strip().casefold() == 'telegram id']
    cell = lambda row, col: str(row[col]).strip() if col < len(row) else ''
    username = lambda row: cell(row, 9).lower().lstrip('@')
    by_name = defaultdict(list)
    for row in troupe[1:]:
        by_name[normalize_name(cell(row, 0))].append(row)
    username_counts = Counter(username(row) for row in troupe[1:] if username(row))
    id_counts = Counter(cell(row, id_columns[0]) for row in troupe[1:]) if len(id_columns) == 1 else Counter()
    voters = db.query(VoterRegistration).all()
    by_id = {v.user_id: v for v in voters}
    by_username = defaultdict(list)
    for voter in voters:
        if voter.username:
            by_username[voter.username.lower().lstrip('@')].append(voter)
    result = []
    for key, actor in sorted(expected.items()):
        rows = by_name[key]
        voter, handle = None, ''
        ambiguous = len(rows) > 1 or len(id_columns) > 1
        if len(rows) == 1 and not ambiguous:
            row = rows[0]
            handle = username(row)
            uid = cell(row, id_columns[0]) if id_columns else ''
            if uid:
                ambiguous = not uid.isdigit() or id_counts[uid] != 1
                if not ambiguous:
                    voter = by_id.get(int(uid))
            elif handle:
                matches = by_username[handle]
                ambiguous = username_counts[handle] != 1 or len(matches) > 1
                if not ambiguous and matches:
                    ambiguous = id_counts[str(matches[0].user_id)] > 0
                    if not ambiguous:
                        voter = matches[0]
        # Names only join the two Sheets tabs; never use a name to bind Telegram identity.
        result.append({**actor, 'username': handle, 'user_id': voter.user_id if voter else None,
                       'ambiguous': ambiguous})
    return result


def queue_cast_memberships(db, campaign, source):
    """Discover missing chat links; only Telegram verification can make them members."""
    from modules.attendance.services import answer_lock
    with answer_lock:
        for actor in cast_identities(db, campaign, source):
            if actor['user_id'] is None:
                continue
            for chat in actor['chats']:
                if db.get(ChatParticipant, (chat, actor['user_id'])) is None:
                    db.add(ChatParticipant(chat_id=chat, user_id=actor['user_id'], status='pending'))
        db.commit()


def unregistered_cast_members(db, campaign, source):
    days_by_chat = defaultdict(set)
    for poll in campaign.polls:
        days_by_chat[poll.telegram_chat_id].update(option_day(o, db) for o in poll.options)
    for days in days_by_chat.values():
        days.discard(None)
    answered = answered_dates(db, set().union(*days_by_chat.values()))
    links = {(r.chat_id, r.user_id): r.status for r in db.query(ChatParticipant)}
    destinations = campaign_destinations(db, json.loads(campaign.show_names))
    result = []
    for actor in cast_identities(db, campaign, source):
        uid = actor['user_id']
        # Report each affected group separately: membership in one does not verify another.
        for chat in sorted(actor['chats']):
            days = days_by_chat[chat]
            missing = sorted(d.isoformat() for d in days if (uid, d) not in answered)
            if not days or (uid is not None and (not missing or links.get((chat, uid)) == 'member')):
                continue
            reason = ('ambiguous_identity' if actor['ambiguous'] else 'not_registered' if uid is None
                      else 'not_member' if links.get((chat, uid)) == 'left' else 'membership_unverified')
            result.append({'name': actor['name'], 'username': actor['username'],
                           'show_names': sorted(actor['shows'].intersection(destinations[chat])),
                           'chat_id': chat, 'can_ping': False, 'reason': reason,
                           'missing_dates': missing if uid is not None else None,
                           'answered_count': len(days) - len(missing) if uid is not None else None,
                           'total_dates': len(days)})
    return result
