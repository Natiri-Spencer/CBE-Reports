"""Short-lived JWTs backed by revocable database sessions."""
import hashlib
import hmac
import logging
import secrets
import time
from datetime import timedelta
from uuid import uuid4
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import or_
from app.core.database import get_db
from app.core.passwords import hasher, verify_password
from app.core.settings import SECRET_KEY, ACCESS_SECONDS, SESSION_SECONDS, ISSUER, AUDIENCE
from app.models.user import User
from app.models.security import AuthSession, RefreshToken, LoginAttempt

ALGORITHM = "HS256"

logger = logging.getLogger("school.security")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def now():
    return int(time.time())

def lock(db):
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

def get_user(db, username):
    return db.query(User).filter_by(username=username).first()

def authenticate_user(db, username, password):
    user = get_user(db, username)
    valid = verify_password(password, user.hashed_password if user else None)
    if not valid or not user.is_active or user.role not in ("teacher", "admin"):
        return None
    if hasher.check_needs_rehash(user.hashed_password):
        user.hashed_password = hasher.hash(password)
    return user

def create_access_token(data, expires_delta: timedelta | None = None):
    issued = now()
    return jwt.encode({**data, "iat": issued, "nbf": issued,
        "exp": issued + (int(expires_delta.total_seconds()) if expires_delta else ACCESS_SECONDS),
        "iss": ISSUER, "aud": AUDIENCE, "jti": str(uuid4()), "type": "access"}, SECRET_KEY, algorithm=ALGORITHM)

def issue_tokens(db, user, session=None):
    issued = now()
    if session is None:
        session = AuthSession(id=str(uuid4()), user_id=user.id, created_at=issued, expires_at=issued + SESSION_SECONDS)
        db.add(session)
        db.flush()
    refresh = secrets.token_urlsafe(48)
    db.add(RefreshToken(digest=hashlib.sha256(refresh.encode()).hexdigest(), session_id=session.id))
    access = create_access_token({"sub": str(user.id), "role": user.role, "sid": session.id, "ver": user.token_version})
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer",
            "expires_in": ACCESS_SECONDS, "refresh_expires_at": session.expires_at}

def invalid_token():
    return HTTPException(401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})

def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db=Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], issuer=ISSUER, audience=AUDIENCE,
            options={"require_exp": True, "require_iat": True, "require_nbf": True, "require_sub": True, "require_jti": True, "require_aud": True, "require_iss": True})
        if payload.get("type") != "access" or not payload.get("sub", "").isdigit():
            raise invalid_token()
        user = db.get(User, int(payload["sub"]))
        session = db.get(AuthSession, payload.get("sid", ""))
        if (not user or not user.is_active or user.role not in ("admin", "teacher")
                or payload.get("role") != user.role or payload.get("ver") != user.token_version
                or not session or session.user_id != user.id or session.revoked_at is not None or session.expires_at <= now()):
            raise invalid_token()
        request.state.session_id = session.id
        return user
    except (JWTError, ValueError, TypeError):
        raise invalid_token() from None

def admin_only(user=Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user

def teacher_only(user=Depends(get_current_user)):
    if user.role != "teacher":
        raise HTTPException(403, "Teachers only")
    return user

def reserve_attempt(db, username, client):
    """Serialize reservations so parallel requests cannot exceed the hash budget."""
    lock(db)
    timestamp = now()
    key = lambda value: hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
    account, source = key("account:" + username.casefold()), key("client:" + client)
    db.query(LoginAttempt).filter(LoginAttempt.occurred_at < timestamp - 7 * 86400).delete()
    recent = db.query(LoginAttempt).filter(LoginAttempt.occurred_at > timestamp - 900)
    account_count = recent.filter(LoginAttempt.account_key == account, LoginAttempt.outcome.in_(["pending", "failure"])).count()
    client_count = recent.filter(LoginAttempt.client_key == source).count()
    if account_count >= 5 or client_count >= 30:
        db.commit()
        logger.warning("authentication_rate_limited")
        raise HTTPException(429, "Too many authentication attempts; try again later", headers={"Retry-After": "900"})
    attempt = LoginAttempt(account_key=account, client_key=source, occurred_at=timestamp, outcome="pending")
    db.add(attempt)
    db.commit()
    return attempt.id

def finish_attempt(db, attempt_id, success):
    db.get(LoginAttempt, attempt_id).outcome = "success" if success else "failure"
    logger.info("authentication_succeeded" if success else "authentication_failed")
