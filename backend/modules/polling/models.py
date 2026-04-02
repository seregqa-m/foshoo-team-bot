from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime


class Poll(Base):
    """Модель опроса"""
    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String, nullable=True)
    calendar_event_id = Column(Integer, ForeignKey("calendar_events.id"), nullable=True)
    created_by = Column(Integer)  # Telegram user ID
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)

    votes = relationship("PollVote", back_populates="poll", cascade="all, delete-orphan")


class PollVote(Base):
    """Модель голоса в опросе"""
    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id"), index=True)
    user_id = Column(Integer)  # Telegram user ID
    answer = Column(String)  # "yes", "no", "maybe"
    voted_at = Column(DateTime, default=datetime.utcnow)

    poll = relationship("Poll", back_populates="votes")
