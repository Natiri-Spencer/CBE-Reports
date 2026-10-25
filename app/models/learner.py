"""Permanent learner identity; names are display values and may repeat."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, String
from app.core.database import Base


class Learner(Base):
    __tablename__ = "learners"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False, index=True)
    class_name = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
