from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean
from datetime import datetime, timezone
from app.db import Base


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    provider = Column(String(50), nullable=False)
    model_id = Column(String(255), nullable=False)
    api_key_encrypted = Column(Text, nullable=True)
    params = Column(JSON, nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
