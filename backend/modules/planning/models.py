from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer
from core.database import Base


class PlanningAssignment(Base):
    """Durable progress for a calendar + schedule assignment (one per date column)."""
    __tablename__ = 'planning_assignments'
    id = Column(String, primary_key=True)
    month = Column(String, index=True, nullable=False)
    column = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String, nullable=False, default='prepared')
    created_at = Column(DateTime, default=datetime.utcnow)


class RepertoireSettings(Base):
    """Month-specific shared draft. '*' contains defaults for unconfigured months."""
    __tablename__ = 'planning_repertoire_settings'
    month = Column(String, primary_key=True)
    revision = Column(Integer, nullable=False, default=0)
    payload = Column(Text, nullable=False)
