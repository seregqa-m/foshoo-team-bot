from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from core.database import Base


class AppUser(Base):
    """Identity observed in signed Telegram Mini App data, not a grant of access."""
    __tablename__ = 'app_users'
    telegram_user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    username = Column(String, default='', nullable=False)
    display_name = Column(String, default='', nullable=False)
    search_text = Column(String, default='', nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SuperAdmin(Base):
    __tablename__ = 'superadmins'
    telegram_user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    granted_by = Column(BigInteger, nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AdminSetup(Base):
    """One-time bootstrap marker, also a database lock for role changes."""
    __tablename__ = 'admin_setup'
    key = Column(String, primary_key=True)
    revision = Column(Integer, default=0, nullable=False)


class AdminAudit(Base):
    __tablename__ = 'admin_audit'
    id = Column(Integer, primary_key=True)
    actor_id = Column(BigInteger, nullable=False)
    target_id = Column(BigInteger, nullable=False)
    action = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
