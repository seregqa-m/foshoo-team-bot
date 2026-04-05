from sqlalchemy import Column, Integer, String, DateTime
from core.database import Base
from datetime import datetime


class ExpenseLog(Base):
    __tablename__ = "expense_log"

    id = Column(Integer, primary_key=True, index=True)
    project = Column(String)
    date = Column(String)       # dd.mm.yyyy как в таблице
    who = Column(String)
    amount = Column(String)
    what = Column(String)
    expense_type = Column(String)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class IncomeLog(Base):
    __tablename__ = "income_log"

    id = Column(Integer, primary_key=True, index=True)
    project = Column(String)
    amount = Column(String)
    what = Column(String)
    date = Column(String)       # dd.mm.yyyy
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReturnsLog(Base):
    """Возвраты — компенсация личных трат. Уменьшают баланс в день выплаты."""
    __tablename__ = "returns_log"

    id = Column(Integer, primary_key=True, index=True)
    project = Column(String)   # Откуда
    who = Column(String)       # Кому
    amount = Column(String)    # Сколько
    date = Column(String)      # dd.mm.yyyy
    created_at = Column(DateTime, default=datetime.utcnow)
