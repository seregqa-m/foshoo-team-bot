from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime


class AvailabilityCampaign(Base):
    """A campaign's publications are retained so earlier answers remain traceable."""
    __tablename__ = "availability_campaigns"

    id = Column(Integer, primary_key=True)
    month = Column(String)           # "2026-05"
    show_names = Column(Text)        # JSON: ["Цианистый калий", "Урод"]
    created_at = Column(DateTime, default=datetime.utcnow)
    request_key = Column(String, nullable=True, index=True)

    polls = relationship("AvailabilityPoll", back_populates="campaign",
                         cascade="all, delete-orphan")


class AvailabilityPoll(Base):
    """Один Telegram-опрос внутри кампании (до 9 дат и «Ни одна из дат»)."""
    __tablename__ = "availability_polls"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("availability_campaigns.id"))
    telegram_poll_id = Column(String, index=True)
    telegram_message_id = Column(Integer)
    telegram_chat_id = Column(BigInteger, nullable=True)
    show_names = Column(Text, nullable=True)
    delivery_state = Column(String, nullable=True)

    campaign = relationship("AvailabilityCampaign", back_populates="polls")
    options = relationship("AvailabilityPollOption", back_populates="poll",
                           cascade="all, delete-orphan")
    votes = relationship("AvailabilityVote", back_populates="poll",
                         cascade="all, delete-orphan")


class AvailabilityPollOption(Base):
    """Дата опции; calendar_event_id сохранён для старых опросов."""
    __tablename__ = "availability_poll_options"

    id = Column(Integer, primary_key=True)
    poll_id = Column(Integer, ForeignKey("availability_polls.id"))
    option_index = Column(Integer)       # 0–9
    calendar_event_id = Column(Integer)  # FK to calendar_events
    selected_date = Column(Date, nullable=True)
    date_label = Column(String)          # текст опции, напр. "сб 17 мая 19:30"

    poll = relationship("AvailabilityPoll", back_populates="options")


class AvailabilityVote(Base):
    """Факт голосования актёра в конкретном опросе (для отслеживания кто не ответил)"""
    __tablename__ = "availability_votes"

    id = Column(Integer, primary_key=True)
    poll_id = Column(Integer, ForeignKey("availability_polls.id"))
    user_id = Column(Integer)
    username = Column(String)
    voted_at = Column(DateTime, default=datetime.utcnow)
    option_ids = Column(Text, nullable=True)

    poll = relationship("AvailabilityPoll", back_populates="votes")
