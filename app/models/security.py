from sqlalchemy import Column, String, Integer, ForeignKey
from app.core.database import Base

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    revoked_at = Column(Integer, nullable=True)

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    digest = Column(String(64), primary_key=True)
    session_id = Column(String(36), ForeignKey("auth_sessions.id"), nullable=False, index=True)
    consumed_at = Column(Integer, nullable=True)

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id = Column(Integer, primary_key=True)
    account_key = Column(String(64), nullable=False, index=True)
    client_key = Column(String(64), nullable=False, index=True)
    occurred_at = Column(Integer, nullable=False, index=True)
    outcome = Column(String(16), nullable=False)
