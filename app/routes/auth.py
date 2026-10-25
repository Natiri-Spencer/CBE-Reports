# routes/auth.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordRequestForm
from typing import Literal
# routes/auth.py (top)
from app.core.auth import pwd_context, authenticate_user, create_access_token
from app.core.database import get_db
from app.models.user import User

router = APIRouter()

class UserCreate(BaseModel):
    username: str
    password: str
    role: Literal["teacher"] = "teacher"



@router.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed_pw = pwd_context.hash(user.password)
    new_user = User(
        username=user.username,
        hashed_password=hashed_pw,
        role="teacher"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "msg": "User created successfully",
        "username": new_user.username,
        "role": new_user.role
    }

@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
def logout():
    return {"msg": "User logged out (delete token client-side)"}
