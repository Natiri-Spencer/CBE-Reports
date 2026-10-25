from sqlalchemy import Column, Integer, String, Float
from app.core.database import Base

class Marks(Base):
    __tablename__ = "marks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)

    # Subject scores
    mathematics = Column(Float, default=0.0)
    pretechnical = Column(Float, default=0.0)
    cre = Column(Float, default=0.0)
    agriculture = Column(Float, default=0.0)
    integrated_science = Column(Float, default=0.0)
    social_studies = Column(Float, default=0.0)
    english = Column(Float, default=0.0)
    kiswahili = Column(Float, default=0.0)
    creativeArts = Column(Float, default=0.0)   # ✅ matches frontend key

    # Optional summary fields (can be populated in routes)
    total = Column(Float, default=0.0)
    average = Column(Float, default=0.0)
    status = Column(String, default="")
    rank = Column(Integer, default=0)
