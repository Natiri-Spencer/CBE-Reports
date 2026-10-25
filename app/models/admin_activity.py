from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class AdminActivity(Base):
    __tablename__ = "admin_activity"

    id = Column(Integer, primary_key=True, index=True)
    actor_username = Column(String(100), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(64), nullable=True)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
