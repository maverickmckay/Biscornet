"""Async job manager for long-running tasks (e.g. large Monte Carlo runs)."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Coroutine

from sqlalchemy.orm import Session

from app.jobs.models import JobRecord


def _new_id() -> str:
    return str(uuid.uuid4())


def create_job(db: Session, job_type: str, graph_id: str | None = None) -> JobRecord:
    record = JobRecord(
        id=_new_id(),
        job_type=job_type,
        status="pending",
        graph_id=graph_id,
        progress=0.0,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_job(db: Session, job_id: str) -> JobRecord | None:
    return db.query(JobRecord).filter(JobRecord.id == job_id).first()


def list_jobs(db: Session, limit: int = 50) -> list[JobRecord]:
    return (
        db.query(JobRecord)
        .order_by(JobRecord.created_at.desc())
        .limit(limit)
        .all()
    )


def _update_job(
    db: Session,
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    result: Any | None = None,
    error: str | None = None,
) -> None:
    record = db.query(JobRecord).filter(JobRecord.id == job_id).first()
    if record is None:
        return
    if status is not None:
        record.status = status
    if progress is not None:
        record.progress = progress
    if result is not None:
        record.result_json = json.dumps(result)
    if error is not None:
        record.error = error
    db.commit()


async def run_job(
    db: Session,
    job_id: str,
    coro: Coroutine[Any, Any, Any],
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Execute *coro* in the background, tracking status in the DB."""
    _update_job(db, job_id, status="running", progress=0.0)
    try:
        result = await coro
        _update_job(db, job_id, status="done", progress=1.0, result=result)
    except Exception as exc:  # noqa: BLE001
        _update_job(db, job_id, status="error", error=str(exc))


def job_to_dict(record: JobRecord) -> dict:
    result = None
    if record.result_json:
        try:
            result = json.loads(record.result_json)
        except Exception:
            result = record.result_json
    return {
        "id": record.id,
        "job_type": record.job_type,
        "status": record.status,
        "graph_id": record.graph_id,
        "progress": record.progress,
        "result": result,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
