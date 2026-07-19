from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from core.database import Base
from datetime import datetime


class AssistantActionLog(Base):
    """Audit trail для действий, выполненных ассистентом."""
    __tablename__ = "assistant_action_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    username = Column(String, nullable=True)
    tool_name = Column(String, index=True)
    args_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    success = Column(Boolean, default=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
