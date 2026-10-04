"""One answer per Telegram person and local calendar day, independent of publications."""
from datetime import datetime
from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String, Text
from core.database import Base


class DayAnswer(Base):
    __tablename__ = 'attendance_days'
    user_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)
    username = Column(String)
    actor_name = Column(String)
    answer = Column(String, nullable=False)
    source = Column(String, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    exported_revision = Column(Integer, default=0, nullable=False)


class AnswerHistory(Base):
    __tablename__ = 'attendance_history'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)
    answer = Column(String, nullable=False)
    source = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AnswerSource(Base):
    """Last accepted state of a publication; duplicate updates cannot regain precedence."""
    __tablename__ = 'attendance_sources'
    source = Column(String, primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    payload = Column(Text, nullable=False)


class PollUpdate(Base):
    __tablename__ = 'attendance_telegram_updates'
    update_id = Column(BigInteger, primary_key=True)
