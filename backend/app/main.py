"""
No Next Move — Backend entry point (Phase 2).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db
from app.api.routes import router
from app.api.doc_routes import router as doc_router
from app.api.log_routes import router as log_router
from app.api.events import router as events_router

app = FastAPI(
    title=settings.app_title,
    description=(
        "Collapse intelligence platform. "
        "Finds where a system has no next move, shows what fails next, "
        "and recommends whether to fix, avoid, hedge, monitor, escalate, or stress-test."
    ),
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()


app.include_router(router, prefix="/api/v1")
app.include_router(doc_router, prefix="/api/v1")
app.include_router(log_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "no-next-move", "version": settings.app_version}
