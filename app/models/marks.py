from sqlalchemy import Column, Integer, String, Float, ForeignKey, CheckConstraint, UniqueConstraint
from app.core.database import Base

class Marks(Base):
    __tablename__ = "marks"
    __table_args__ = (
        UniqueConstraint("learner_id", "class_name", "academic_year", "term", name="uq_marks_learner_period"),
        CheckConstraint("(academic_year = 0 AND term = 0) OR (academic_year BETWEEN 2000 AND 2200 AND term BETWEEN 1 AND 3)", name="ck_marks_period"),
        CheckConstraint("length(trim(class_name)) > 0", name="ck_marks_class"),
        *[CheckConstraint(f"{field} >= 0 AND {field} <= 100", name=f"ck_marks_{field}") for field in (
            "mathematics", "pretechnical", "cre", "agriculture", "integrated_science", "social_studies", "english", "kiswahili", "creative_arts")],
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    learner_id = Column(String(36), ForeignKey("learners.id"), nullable=False, index=True)
    class_name = Column(String(50), nullable=False)
    academic_year = Column(Integer, nullable=False)
    term = Column(Integer, nullable=False)

    # Subject scores
    mathematics = Column(Float, nullable=False)
    pretechnical = Column(Float, nullable=False)
    cre = Column(Float, nullable=False)
    agriculture = Column(Float, nullable=False)
    integrated_science = Column(Float, nullable=False)
    social_studies = Column(Float, nullable=False)
    english = Column(Float, nullable=False)
    kiswahili = Column(Float, nullable=False)
    creative_arts = Column(Float, nullable=False)

    # Optional summary fields (can be populated in routes)
    total = Column(Float, default=0.0)
    average = Column(Float, default=0.0)
    status = Column(String, default="")
    rank = Column(Integer, default=0)
