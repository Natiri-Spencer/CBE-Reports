from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.learner import Learner
from app.core.idempotency import IdempotencyKey, execute_once

router = APIRouter()


class LearnerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    class_name: str = Field(min_length=1, max_length=50)


class LearnerRecord(LearnerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value):
        # SQLite drops timezone metadata from DateTime columns. Stored values
        # are UTC; make that explicit at the API boundary (RFC 3339).
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class LearnerPage(BaseModel):
    items: list[LearnerRecord]
    total: int
    limit: int
    offset: int


@router.get("", response_model=LearnerPage, operation_id="list_learners")
def list_learners(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=255)] = None,
    class_name: str | None = None,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    query = db.query(Learner)
    if search:
        # Treat SQL LIKE wildcard characters as ordinary search text.
        query = query.filter(Learner.name.icontains(search.strip(), autoescape=True))
    if class_name:
        query = query.filter(Learner.class_name == class_name)
    total = query.count()
    return {"items": query.order_by(Learner.name, Learner.id).offset(offset).limit(limit).all(),
            "total": total, "limit": limit, "offset": offset}


@router.post("", response_model=LearnerRecord, operation_id="create_learner", status_code=201)
def create_learner(record: LearnerCreate, idempotency_key: IdempotencyKey,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    def create():
        learner = Learner(**record.model_dump())
        db.add(learner)
        db.flush()
        return LearnerRecord.model_validate(learner).model_dump(mode="json")
    return execute_once(db, user.id, "learners:create", idempotency_key, record.model_dump(), create)


@router.get("/{learner_id}", response_model=LearnerRecord, operation_id="get_learner")
def get_learner(learner_id: UUID, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    learner = db.get(Learner, str(learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    return learner
