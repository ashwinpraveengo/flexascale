"""
FastAPI application factory for FlexaScale REST API & Dashboard.
"""

from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from flexascale.api.routes import router as api_router
from flexascale.api.state_store import APIStateStore, get_state_store, set_state_store


def create_app(
    mock: bool = True,
    state_store: APIStateStore | None = None,
) -> FastAPI:
    """
    Creates and configures the FastAPI application instance.
    """
    if state_store is not None:
        set_state_store(state_store)
    else:
        # Initialize default store
        get_state_store(mock=mock)

    app = FastAPI(
        title="FlexaScale Autoscaling Controller & Dashboard API",
        description="REST API for real-time telemetry, RL decisions, dependency graph inference, and dynamic SLO configuration.",
        version="0.1.0",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes
    app.include_router(api_router)

    # Root health endpoint
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "flexascale-api"}

    # Mount static assets if built
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
