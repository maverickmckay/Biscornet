"""ORM model for async job tracking."""
from __future__ import annotations

import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.db.database import Base


class JobRecord(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)          # UUID string
    job_type = Column(String, nullable=False)       # e.g. "monte_carlo"
    status = Column(String, nullable=False, default="pending")  # pending|running|done|error
    graph_id = Column(String, nullable=True)
    progress = Column(Float, default=0.0)           # 0.0–1.0
    result_json = Column(Text, nullable=True)       # JSON result blob
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
