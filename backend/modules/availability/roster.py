"""Expose cast members missing from the verified Telegram roster; never ping them."""
import json
from collections import Counter, defaultdict

from modules.attendance.models import ChatParticipant, DayAnswer, VoterRegistration
from modules.attendance.services import option_day
from modules.theater.routing import campaign_destinations, sheet_show_names
from modules.theater.services import normalize_name


def unregistered_cast_members(db, campaign, source):
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
    members = {(r.chat_id, r.user_id) for r in db.query(ChatParticipant).filter_by(status='member')}
    days = {option_day(o, db) for p in campaign.polls for o in p.options} - {None}
    answered = defaultdict(set)
    for answer in db.query(DayAnswer).filter(DayAnswer.day.in_(days), DayAnswer.answer != 'retracted'):
        answered[answer.user_id].add(answer.day)

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
                    voter = matches[0]
        # Names only join the two Sheets tabs; never use a name to bind Telegram identity.
        if voter and (any((chat, voter.user_id) in members for chat in actor['chats'])
                      or (days and days <= answered[voter.user_id])):
            continue
        result.append({'name': actor['name'], 'username': handle,
                       'show_names': sorted(actor['shows']), 'can_ping': False,
                       'reason': 'ambiguous_identity' if ambiguous else 'membership_unverified' if voter else 'not_registered'})
    return result
