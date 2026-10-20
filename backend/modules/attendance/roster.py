"""Group-based recipient lists and date totals, independent of Sheets roles."""
from html import escape
from .models import ChatParticipant, DayAnswer, VoterRegistration


def members(db, chat_id, *, active_only=True):
    query = db.query(ChatParticipant, VoterRegistration).join(
        VoterRegistration, VoterRegistration.user_id == ChatParticipant.user_id).filter(
            ChatParticipant.chat_id == chat_id)
    if active_only:
        query = query.filter(ChatParticipant.status == 'member')
    return [{'user_id': person.user_id, 'name': person.actor_name or person.display_name,
             'username': person.username, 'status': link.status,
             'checked_at': link.checked_at.isoformat() + 'Z' if link.checked_at else None,
             'revision': link.revision}
            for link, person in query.order_by(VoterRegistration.user_id).all()]


def missing_members(db, chat_id, days):
    days = set(days)
    rows = db.query(DayAnswer).filter(DayAnswer.day.in_(days)).all()
    known = {(row.user_id, row.day) for row in rows}
    answered = {(row.user_id, row.day) for row in rows if row.answer != 'retracted'}
    from modules.polling.models import Poll, PollVote
    for vote, poll in db.query(PollVote, Poll).join(Poll, Poll.id == PollVote.poll_id).filter(
            Poll.selected_date.in_(days)):
        pair = (vote.user_id, poll.selected_date)
        if pair not in known and vote.answer != 'retracted':
            answered.add(pair)
    return [person for person in members(db, chat_id)
            if any((person['user_id'], day) not in answered for day in days)]


def attendance_totals(db, chat_id, day):
    people = members(db, chat_id)
    answers = {row.user_id: row.answer for row in db.query(DayAnswer).filter_by(day=day)}
    result = {'total': len(people), 'yes': 0, 'no': 0, 'unknown': 0, 'unanswered': 0}
    for person in people:
        answer = answers.get(person['user_id'])
        result[answer if answer in ('yes', 'no', 'unknown') else 'unanswered'] += 1
    result['scope'] = 'registered_chat_participants'
    return result


def mention_messages(heading, people, links=()):
    """ID mentions work without usernames; HTML names cannot inject markup."""
    # Bound both Telegram's text limit and entity count.
    for offset in range(0, len(people), 20):
        mentions = ' '.join(f'<a href="tg://user?id={p["user_id"]}">{escape(p["name"][:80])}</a>'
                            for p in people[offset:offset + 20])
        yield escape(heading) + '\n' + mentions + ('\n\n' + '\n'.join(links) if links else '')
