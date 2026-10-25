from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.core.database import Base


class RequestReceipt(Base):
    __tablename__ = "request_receipts"
    __table_args__ = (UniqueConstraint("actor_id", "operation", "key", name="uq_request_receipt"),)

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    operation = Column(String(80), nullable=False)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_body = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
