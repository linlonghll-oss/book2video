from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db import Base


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, ForeignKey("notes.id"), nullable=False)
    type = Column(String(50), nullable=False)
    url = Column(String(1024), nullable=True)
    local_path = Column(String(1024), nullable=True)
    prompt = Column(Text, nullable=True)
    meta_data = Column("metadata", JSON, nullable=True)
    duration = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    note = relationship("Note", back_populates="materials")
