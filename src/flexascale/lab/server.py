"""
HTTP server for the FlexaScale Live Autoscaling Lab dashboard.

Same-origin only (no CORS), intended to bind to 127.0.0.1. The API exposes a
fixed set of experiment operations with validated, bounded parameters; it
never accepts commands, file paths or Kubernetes credentials from the client.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from flexascale.lab.experiments import CONTROLLERS, LIMITS, ROOT, SCENARIOS, ExperimentRequest, Lab

STATIC_DIR = Path(__file__).parent / "static"


class StartBody(BaseModel):
    app: str
    controller: str
    scenario: str
    users: int = Field(40, ge=LIMITS["users"][0], le=LIMITS["users"][1])
    spawn_rate: float = Field(5.0, ge=LIMITS["spawn_rate"][0], le=LIMITS["spawn_rate"][1])
    duration: int = Field(300, ge=LIMITS["duration"][0], le=LIMITS["duration"][1])
    reset_replicas: bool = True
    shadow: bool = True
    policy_variant: Optional[str] = None
    hpa_cpu_target_pct: Optional[int] = None
    hpa_scale_down_window_s: Optional[int] = None
    block: Optional[str] = Field(None, max_length=64)


def _model_cards() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for card in sorted((ROOT / "models").glob("*/model_card.json")):
        try:
            out[card.parent.name] = json.loads(card.read_text())
        except ValueError:
            continue
    for key, name in (("_simulation_evaluation", "simulation_evaluation.json"),
                      ("_simulation_evaluation_v4", "simulation_evaluation_v4.json"),
                      ("_simulation_evaluation_v5", "simulation_evaluation_v5.json"),
                      ("_simulation_evaluation_v6", "simulation_evaluation_v6.json")):
        sim = ROOT / "reports" / name
        if sim.is_file():
            try:
                out[key] = json.loads(sim.read_text())
            except ValueError:
                pass
    return out


def create_lab_app(lab: Optional[Lab] = None) -> FastAPI:
    holder: Dict[str, Lab] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        holder["lab"] = lab or Lab()
        yield
        holder["lab"].shutdown()

    app = FastAPI(title="FlexaScale Live Autoscaling Lab", version="1.0.0", lifespan=lifespan)

    def L() -> Lab:
        return holder["lab"]

    @app.get("/api/lab/health")
    def health():
        return {"status": "ok", "time": time.time()}

    @app.get("/api/lab/overview")
    def overview():
        lab_ = L()
        active = lab_.active
        return {
            "cluster": lab_.cluster_health(),
            "apps": lab_.apps(),
            "active": {"id": active.id, "state": active.state} if active else None,
            "processes": lab_.pm.list(),
        }

    @app.get("/api/lab/scenarios")
    def scenarios():
        return {"scenarios": SCENARIOS, "controllers": list(CONTROLLERS), "limits": LIMITS,
                "variants": {name: sorted(spec.variants) for name, spec in L().cfg.apps.items()}}

    @app.get("/api/lab/apps/{app_name}/live")
    def live(app_name: str):
        if app_name not in L().cfg.apps:
            raise HTTPException(404, f"unknown app '{app_name}'")
        return L().live(app_name)

    @app.post("/api/lab/experiments")
    def start(body: StartBody):
        try:
            exp = L().start(ExperimentRequest(**body.model_dump()))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"id": exp.id, "state": exp.state}

    @app.post("/api/lab/experiments/stop")
    def stop():
        exp = L().stop()
        if exp is None:
            raise HTTPException(404, "no experiment")
        return {"id": exp.id, "state": exp.state}

    @app.get("/api/lab/experiments/active")
    def active():
        exp = L().active
        if exp is None:
            return JSONResponse({"active": None})
        return {"active": exp.snapshot()}

    @app.get("/api/lab/experiments")
    def runs():
        return {"runs": L().runs()}

    @app.get("/api/lab/experiments/{run_id}")
    def run(run_id: str):
        try:
            return L().run(run_id)
        except KeyError:
            raise HTTPException(404, "unknown run")

    @app.get("/api/lab/compare")
    def compare(baseline: str, candidate: str):
        try:
            return L().compare(baseline, candidate)
        except KeyError:
            raise HTTPException(404, "unknown run")

    @app.get("/api/lab/benchmark")
    def bench(app: Optional[str] = None):
        return L().benchmark(app)

    @app.get("/api/lab/models")
    def models():
        return _model_cards()

    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            return FileResponse(STATIC_DIR / "index.html")

    return app
