from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
import hashlib
from app.core.auth import (authenticate_user, issue_tokens, get_current_user, admin_only, lock,
                           reserve_attempt, finish_attempt, now, invalid_token)
from app.core.passwords import hash_password
from app.core.database import get_db
from app.models.user import User
from app.models.security import AuthSession, RefreshToken, LoginAttempt

router = APIRouter()

class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100, pattern=r"^\S(?:.*\S)?$")
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["teacher"] = "teacher"

class UserRegistered(BaseModel):
    msg: str
    username: str
    role: Literal["teacher"]

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int
    refresh_expires_at: int

class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=32, max_length=256)

class LogoutResponse(BaseModel):
    msg: str

class AccountStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool

class AccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    is_active: bool

class Monitoring(BaseModel):
    window_seconds: int
    failed: int
    succeeded: int
    pending: int

@router.post("/signup", response_model=UserRegistered, status_code=202, operation_id="signup")
def signup(user: UserCreate, request: Request, db=Depends(get_db)):
    attempt = reserve_attempt(db, user.username, request.client.host if request.client else "unknown")
    lock(db)
    existing = db.query(User).filter_by(username=user.username).first()
    if not existing:
        db.add(User(username=user.username, hashed_password=hash_password(user.password), role="teacher", is_active=False))
    db.get(LoginAttempt, attempt).outcome = "registration"
    db.commit()
    return {"msg": "Account request received. An administrator must approve access.", "username": user.username, "role": "teacher"}

@router.post("/token", response_model=TokenResponse, operation_id="login")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    attempt = reserve_attempt(db, form_data.username, request.client.host if request.client else "unknown")
    lock(db)
    user = authenticate_user(db, form_data.username, form_data.password) if len(form_data.password) <= 1024 and len(form_data.username) <= 100 else None
    finish_attempt(db, attempt, user is not None)
    if not user:
        db.commit()
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    result = issue_tokens(db, user)
    db.commit()
    return result

@router.post("/refresh", response_model=TokenResponse, operation_id="refresh_session")
def refresh(body: RefreshRequest, db=Depends(get_db)):
    lock(db)
    token = db.get(RefreshToken, hashlib.sha256(body.refresh_token.encode()).hexdigest())
    session = db.get(AuthSession, token.session_id) if token else None
    if not session or session.revoked_at is not None or session.expires_at <= now():
        raise invalid_token()
    if token.consumed_at is not None:
        session.revoked_at = now()
        db.commit()
        raise invalid_token()
    user = db.get(User, session.user_id)
    if not user or not user.is_active or user.role not in ("admin", "teacher"):
        raise invalid_token()
    token.consumed_at = now()
    result = issue_tokens(db, user, session)
    db.commit()
    return result

@router.post("/logout", response_model=LogoutResponse, operation_id="logout")
def logout(request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    lock(db)
    db.get(AuthSession, request.state.session_id).revoked_at = now()
    db.commit()
    return {"msg": "Session revoked"}

@router.post("/logout-refresh", response_model=LogoutResponse, operation_id="logout_refresh")
def logout_refresh(body: RefreshRequest, db=Depends(get_db)):
    # The opaque refresh token is authentication for logout after access expiry.
    lock(db)
    token = db.get(RefreshToken, hashlib.sha256(body.refresh_token.encode()).hexdigest())
    if token:
        db.get(AuthSession, token.session_id).revoked_at = now()
    db.commit()
    return {"msg": "Session revoked"}

@router.get("/accounts", response_model=list[AccountView], operation_id="list_accounts")
def accounts(offset: int = 0, limit: int = 50, admin=Depends(admin_only), db=Depends(get_db)):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid pagination")
    return db.query(User).order_by(User.id).offset(offset).limit(limit).all()

@router.put("/accounts/{user_id}/status", response_model=AccountView, operation_id="set_account_status")
def account_status(user_id: int, body: AccountStatus, admin=Depends(admin_only), db=Depends(get_db)):
    lock(db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Account not found")
    if not body.is_active and user.role == "admin" and user.is_active:
        if db.query(User).filter_by(role="admin", is_active=True).count() <= 1:
            raise HTTPException(409, "The last active administrator cannot be disabled")
    user.is_active = body.is_active
    user.token_version += 1
    db.query(AuthSession).filter_by(user_id=user.id, revoked_at=None).update({"revoked_at": now()})
    db.commit()
    return user

@router.get("/monitoring", response_model=Monitoring, operation_id="authentication_monitoring")
def monitoring(admin=Depends(admin_only), db=Depends(get_db)):
    recent = db.query(LoginAttempt).filter(LoginAttempt.occurred_at > now() - 86400)
    return {"window_seconds": 86400, "failed": recent.filter_by(outcome="failure").count(),
            "succeeded": recent.filter_by(outcome="success").count(), "pending": recent.filter_by(outcome="pending").count()}
