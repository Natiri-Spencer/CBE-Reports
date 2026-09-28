from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.core.auth import (
    pwd_context,
    authenticate_user,
    create_access_token,
    get_db,
)
from app.models.user import User

# -------------------------------
# Router (no prefix here)
# -------------------------------
router = APIRouter()

# -------------------------------
# Pydantic model for signup
# -------------------------------
class UserCreate(BaseModel):
    username: str
    password: str
    role: str

# -------------------------------
# Signup
# -------------------------------
@router.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_pw = pwd_context.hash(user.password)
    new_user = User(
        username=user.username,
        hashed_password=hashed_pw,
        role=user.role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"msg": "User created", "username": new_user.username, "role": new_user.role}

# -------------------------------
# Login
# -------------------------------
@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}

# -------------------------------
# Logout
# -------------------------------
@router.post("/logout")
def logout():
    # JWT logout is handled client-side by deleting the token
    return {"msg": "User logged out (delete token client-side)"}
