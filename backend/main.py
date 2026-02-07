"""
Sentinel API — Incident analysis and pattern detection platform.

App creation, middleware, lifespan, and route registration.
All route handlers live in backend/routes/.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import register_routes

logger = logging.getLogger(__name__)

USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    if USE_DATABASE:
        from backend.database import get_pool
        await get_pool()
        logger.info("Database connection pool initialized")

        if not USE_CELERY:
            from backend.services.job_executor import get_executor
            executor = get_executor()
            await executor.start()
            logger.info("Background job executor started (in-process)")
        else:
            logger.info("Celery mode enabled — skipping in-process job executor")

        from backend.jobs_ws import job_update_manager
        await job_update_manager.start()

    yield

    if USE_DATABASE:
        from backend.jobs_ws import job_update_manager
        await job_update_manager.stop()

        if not USE_CELERY:
            from backend.services.job_executor import get_executor
            executor = get_executor()
            await executor.stop()
            logger.info("Background job executor stopped")

        from backend.database import close_pool
        await close_pool()
        logger.info("Database connection pool closed")


app = FastAPI(
    title="Sentinel API",
    description="Incident analysis and pattern detection platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routes(app)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    status = {"status": "healthy", "database": "disabled"}

    if USE_DATABASE:
        try:
            from backend.database import check_connection
            db_healthy = await check_connection()
            status["database"] = "connected" if db_healthy else "error"
        except Exception as e:
            status["database"] = f"error: {str(e)}"

    return status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
