#!/usr/bin/env python3
"""
Orchestrator microservice -- HTTP wrapper + distributed driver.

- GET  /status/{id}        -> pipeline status from on-chain state
- POST /run-all/{id}        -> drive the whole workflow across the actor services

The run-all response carries BOTH a conclusion (per stage: status/actor/tx) AND
the full step-by-step "log" of each stage, so you can show either the summary or
the detailed Step 3->7 execution.

Run locally (from repo root):
    uvicorn api.orchestrator_api:app --app-dir src --port 8000

Service URLs (override via env for Docker):
    CLEANING_URL (default http://localhost:8001)
    TRAINING_URL (default http://localhost:8002)
    REVIEW_URL   (default http://localhost:8003)
"""

import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from orchestrator import stage_defs, compute_status
from blockchain.multiactor_backend import MultiActorBackend

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]

SERVICE_URLS = {
    "cleaning": os.getenv("CLEANING_URL", "http://localhost:8001"),
    "training": os.getenv("TRAINING_URL", "http://localhost:8002"),
    "model":    os.getenv("REVIEW_URL",   "http://localhost:8003"),
}

app = FastAPI(title="Pipeline Orchestrator")


@app.get("/health")
def health():
    return {"status": "ok", "service": "orchestrator", "services": SERVICE_URLS}


@app.get("/status/{pipeline_id}")
def status(pipeline_id: int):
    backend = MultiActorBackend(pipeline_id=pipeline_id)
    stages = stage_defs(pipeline_id)
    st = compute_status(backend, stages)
    return {
        "pipeline_id": pipeline_id,
        "stages": [
            {"stage": s["name"], "status": st[s["name"]], "assigned_to": s["who"]}
            for s in stages
        ],
    }


def _certify_roots(pipeline_id: int) -> dict:
    """Admin certifies the root stages (dataset + environment) via subprocess."""
    result = subprocess.run(
        [sys.executable, "src/certify_root_on_v2.py", "--pipeline-id", str(pipeline_id)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={
            "stage": "root(dataset+environment)",
            "error": "root certification failed",
            "log": result.stdout,
            "stderr_tail": result.stderr[-1500:],
        })
    return {
        "stage": "root(dataset+environment)",
        "status": "certified",
        "by": "admin",
        "log": result.stdout,
    }


def _call_service(stage: str, pipeline_id: int) -> dict:
    """Ask an actor microservice to run its stage."""
    url = SERVICE_URLS[stage] + "/run"
    try:
        resp = requests.post(url, json={"pipeline_id": pipeline_id}, timeout=300)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail={
            "stage": stage, "error": f"could not reach {url}: {exc}"})
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail={
            "stage": stage, "error": "actor service rejected", "detail": resp.json()})
    body = resp.json()
    return {
        "stage": stage,
        "status": body.get("status"),
        "actor_address": body.get("actor_address"),
        "tx_id": body.get("tx_id"),
        "log": body.get("log"),        # full step-by-step detail from the actor
    }


@app.post("/run-all/{pipeline_id}")
def run_all(pipeline_id: int):
    """Drive the whole workflow: admin roots, then the three actor services.

    Each step carries a conclusion (status/actor/tx) AND its full 'log'.
    """
    results = [_certify_roots(pipeline_id)]
    for stage in ("cleaning", "training", "model"):
        results.append(_call_service(stage, pipeline_id))
    return {"pipeline_id": pipeline_id, "status": "complete", "steps": results}