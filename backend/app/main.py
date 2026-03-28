"""
No Next Move — Backend entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(
    title="No Next Move",
    description=(
        "Collapse intelligence platform. "
        "Finds where a system has no next move, shows what fails next, "
        "and recommends whether to fix, avoid, hedge, monitor, escalate, or stress-test."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "no-next-move"}
