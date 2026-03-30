"""
NodeHistoryRecord — time-series state readings for graph nodes.
Powers the ThresholdEngine's timing projections.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, Index

from app.db.database import Base


class NodeHistoryRecord(Base):
    __tablename__ = "node_history"

    id = Column(String, primary_key=True)
    graph_id = Column(String, nullable=False, index=True)
    node_id = Column(String, nullable=False, index=True)
    load = Column(Float, nullable=False, default=0.0)
    reliability = Column(Float, nullable=False, default=1.0)
    stress = Column(Float, nullable=False, default=0.0)
    source = Column(String, nullable=False, default="api")   # api|bootstrap|telemetry|manual
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_node_history_graph_node", "graph_id", "node_id"),
    )
