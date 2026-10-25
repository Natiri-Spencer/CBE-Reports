# app/core/auth.py
import os
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.models.user import User

# -------------------------------
# JWT Config
# -------------------------------
ENVIRONMENT = os.getenv("ENV", "DEV").upper()
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    if ENVIRONMENT == "PROD":
        raise RuntimeError("JWT_SECRET_KEY must be set when ENV=PROD")
    SECRET_KEY = "development-only-secret-change-before-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# Password hashing (Argon2)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# -------------------------------
# Password Helpers
# -------------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# -------------------------------
# User Helpers
# -------------------------------
def get_user(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()

def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user(db, username)
    if not user or not verify_password(password, getattr(user, "hashed_password", "")):
        return None
    return user

# -------------------------------
# JWT Helpers
# -------------------------------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": int(expire.timestamp())})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        user = get_user(db, username)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# -------------------------------
# Role-based Access
# -------------------------------
def admin_only(user: User = Depends(get_current_user)):
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user

def teacher_only(user: User = Depends(get_current_user)):
    if getattr(user, "role", None) != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return True
