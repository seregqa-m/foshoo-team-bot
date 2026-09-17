from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
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
