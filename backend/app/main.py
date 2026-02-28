from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(
    title="Treasure Finance Tracker",
    version="0.1.0",
    description="Self-hosted personal finance tracker",
)

app.include_router(health_router, prefix="/api")
