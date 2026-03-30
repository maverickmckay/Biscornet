"""
No Next Move — Backend entry point (Phase 3).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db
from app.api.routes import router
from app.api.doc_routes import router as doc_router
from app.api.log_routes import router as log_router
from app.api.events import router as events_router
from app.api.market_routes import router as market_router
from app.api.feedback_routes import router as feedback_router
from app.api.agent_routes import router as agent_router
from app.auth.routes import router as auth_router
from app.api.telemetry_routes import router as telemetry_router
from app.api.oracle_routes import router as oracle_router
from app.api.backtest_routes import router as backtest_router

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
app.include_router(market_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(telemetry_router, prefix="/api/v1")
app.include_router(oracle_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "no-next-move", "version": settings.app_version}
