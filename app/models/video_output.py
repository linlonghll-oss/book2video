from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db import Base


class VideoOutput(Base):
    __tablename__ = "video_outputs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, ForeignKey("notes.id"), nullable=False)
    url = Column(String(1024), nullable=True)
    local_path = Column(String(1024), nullable=True)
    duration = Column(Float, nullable=True)
    resolution = Column(String(20), nullable=True)
    file_size = Column(Integer, nullable=True)
    meta_data = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    note = relationship("Note", back_populates="video_outputs")
