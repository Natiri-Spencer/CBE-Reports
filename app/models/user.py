from sqlalchemy import Column, Integer, String, Boolean, true, text
from app.core.database import Base  # ✅ make sure you import Base from your updated database.py

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())
    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
