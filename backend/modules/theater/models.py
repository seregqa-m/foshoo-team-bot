"""Shared show catalog and explicitly configured Telegram destinations."""
from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from core.database import Base


class TheaterChat(Base):
    __tablename__ = 'theater_chats'
    telegram_chat_id = Column(BigInteger, primary_key=True, autoincrement=False)
    title = Column(String, nullable=False)
    checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TheaterShow(Base):
    __tablename__ = 'theater_shows'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, unique=True)
    telegram_chat_id = Column(BigInteger, ForeignKey('theater_chats.telegram_chat_id'), nullable=True)
    revision = Column(Integer, nullable=False, default=0)


class TheaterShowAlias(Base):
    """Keep imported spellings attached to a stable show after a rename."""
    __tablename__ = 'theater_show_aliases'
    normalized_name = Column(String, primary_key=True)
    show_id = Column(Integer, ForeignKey('theater_shows.id'), nullable=False, index=True)


class TheaterAudit(Base):
    __tablename__ = 'theater_audit'
    id = Column(Integer, primary_key=True)
    actor_id = Column(BigInteger, nullable=False)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
