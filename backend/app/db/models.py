"""
SQLAlchemy ORM models.
Graphs and analyses are stored as JSON blobs alongside indexed metadata columns.
This avoids a complex multi-table schema while remaining trivially portable to
Postgres JSONB when needed.
"""
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, func

from app.db.database import Base


class GraphRecord(Base):
    __tablename__ = "graphs"

    id = Column(String, primary_key=True)
    name = Column(String, index=True, nullable=False)
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    graph_json = Column(Text, nullable=False)


class AnalysisRecord(Base):
    __tablename__ = "analyses"

    id = Column(String, primary_key=True)
    graph_id = Column(String, ForeignKey("graphs.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at = Column(DateTime, default=func.now())
    analysis_json = Column(Text, nullable=False)
