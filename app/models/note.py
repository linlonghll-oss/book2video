from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db import Base


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    refined_title = Column(String(255), nullable=True)
    refined_body = Column(Text, nullable=True)
    styled_body = Column(Text, nullable=True)  # AI-designed rich text (JSON)
    status = Column(String(50), default="draft")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    folder = relationship("Folder", back_populates="notes")
    scripts = relationship("Script", back_populates="note", cascade="all, delete-orphan")
    materials = relationship("Material", back_populates="note", cascade="all, delete-orphan")
    video_outputs = relationship("VideoOutput", back_populates="note", cascade="all, delete-orphan")
