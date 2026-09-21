from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, UniqueConstraint
from core.database import Base


class ModerationComment(Base):
    __tablename__ = 'moderation_comments'
    __table_args__ = (UniqueConstraint('chat_id', 'message_id'),)
    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    recipient_id = Column(BigInteger, nullable=False)
    author_id = Column(BigInteger)
    author = Column(String, nullable=False, default='')
    text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    last_update_id = Column(BigInteger, nullable=False)
    message_time = Column(BigInteger, nullable=False)
    reason = Column(Text, nullable=False, default='')
    state = Column(String, nullable=False, default='checking')
    notification_id = Column(BigInteger)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
