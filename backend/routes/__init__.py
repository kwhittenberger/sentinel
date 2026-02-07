"""
Route registration for Sentinel API.
Includes all APIRouter modules extracted from main.py.
"""

from fastapi import FastAPI

from backend.routes import (
    incidents,
    curation,
    admin_incidents,
    jobs,
    settings,
    feeds,
    domains,
    types_prompts,
    events_actors,
    analytics,
    extraction,
    cases,
    testing,
    recidivism,
)


def register_routes(app: FastAPI) -> None:
    """Register all route modules with the FastAPI app."""
    app.include_router(incidents.router)
    app.include_router(curation.router)
    app.include_router(admin_incidents.router)
    app.include_router(jobs.router)
    app.include_router(settings.router)
    app.include_router(feeds.router)
    app.include_router(domains.router)
    app.include_router(types_prompts.router)
    app.include_router(events_actors.router)
    app.include_router(analytics.router)
    app.include_router(extraction.router)
    app.include_router(cases.router)
    app.include_router(testing.router)
    app.include_router(recidivism.router)
