"""Typed request/response contracts used to publish the FastAPI OpenAPI schema."""
from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Scores(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True, from_attributes=True)
    mathematics: float = Field(ge=0, le=100)
    pretechnical: float = Field(ge=0, le=100)
    cre: float = Field(ge=0, le=100)
    agriculture: float = Field(ge=0, le=100)
    integrated_science: float = Field(ge=0, le=100)
    social_studies: float = Field(ge=0, le=100)
    english: float = Field(ge=0, le=100)
    kiswahili: float = Field(ge=0, le=100)
    creative_arts: float = Field(ge=0, le=100)


class StudentMarks(Scores):
    learner_id: UUID
    class_name: str = Field(min_length=1, max_length=50)
    academic_year: int = Field(ge=2000, le=2200)
    term: int = Field(ge=1, le=3)


class MarksSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    students: list[StudentMarks] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_records(self):
        identities = [(row.learner_id, row.class_name, row.academic_year, row.term) for row in self.students]
        if len(identities) != len(set(identities)):
            raise ValueError("Each learner/class/year/term may appear only once per submission")
        return self


class MarkRecord(Scores):
    id: int
    learner_id: UUID
    name: str
    class_name: str
    academic_year: int
    term: int
    total: float
    average: float
    status: str
    rank: int


class MarksSaved(BaseModel):
    message: str
    results: list[MarkRecord]
