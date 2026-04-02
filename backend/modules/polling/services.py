"""
Сервис для работы с опросами
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import Poll, PollVote

logger = logging.getLogger(__name__)


class PollingService:
    """Сервис управления опросами"""

    def __init__(self, db: Session):
        self.db = db

    def create_poll(
        self,
        title: str,
        created_by: int,
        expires_in_hours: int = 24,
        description: str = None,
        calendar_event_id: int = None
    ) -> Poll:
        """Создать новый опрос"""
        poll = Poll(
            title=title,
            description=description,
            calendar_event_id=calendar_event_id,
            created_by=created_by,
            expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
        )
        self.db.add(poll)
        self.db.commit()
        self.db.refresh(poll)
        logger.info(f"Created poll: {poll.id}")
        return poll

    def get_poll(self, poll_id: int) -> Poll:
        """Получить опрос по ID"""
        return self.db.query(Poll).filter(Poll.id == poll_id).first()

    def get_active_polls(self) -> list[Poll]:
        """Получить активные опросы"""
        now = datetime.utcnow()
        return self.db.query(Poll).filter(
            Poll.is_active == True,
            Poll.expires_at > now
        ).all()

    def vote(self, poll_id: int, user_id: int, answer: str) -> PollVote:
        """Добавить голос в опрос"""
        existing_vote = self.db.query(PollVote).filter(
            PollVote.poll_id == poll_id,
            PollVote.user_id == user_id
        ).first()

        if existing_vote:
            existing_vote.answer = answer
        else:
            existing_vote = PollVote(
                poll_id=poll_id,
                user_id=user_id,
                answer=answer
            )
            self.db.add(existing_vote)

        self.db.commit()
        return existing_vote

    def get_poll_results(self, poll_id: int) -> dict:
        """Получить результаты опроса"""
        poll = self.get_poll(poll_id)
        if not poll:
            return None

        votes = self.db.query(PollVote).filter(PollVote.poll_id == poll_id).all()

        results = {"yes": 0, "no": 0, "maybe": 0}
        for vote in votes:
            if vote.answer in results:
                results[vote.answer] += 1

        return {
            "poll_id": poll_id,
            "title": poll.title,
            "results": results,
            "total_votes": len(votes),
            "is_active": poll.is_active,
            "expires_at": poll.expires_at.isoformat()
        }
