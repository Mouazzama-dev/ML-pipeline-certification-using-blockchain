#!/usr/bin/env python3
"""
Orchestrator microservice -- HTTP wrapper + distributed driver + admin API.

Endpoints
  GET  /health
  GET  /actors                          -> admin + actor addresses/roles (for the UI)
  GET  /status/{id}                     -> pipeline status from on-chain state
  POST /pipeline/create                 -> ADMIN: create pipeline + roles (setup)
  POST /pipeline/{id}/certify-roots     -> ADMIN: certify dataset + environment
  POST /pipeline/{id}/run/{stage}       -> run a single actor stage (cleaning/training/model)
  POST /run-all/{id}                    -> drive the whole workflow

The run responses carry BOTH a conclusion (status/actor/tx) and the full log.

Run locally (from repo root):
    uvicorn api.orchestrator_api:app --app-dir src --port 8000

Service URLs (override via env for Docker):
    CLEANING_URL (default http://localhost:8001)
    TRAINING_URL (default http://localhost:8002)
    REVIEW_URL   (default http://localhost:8003)
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from orchestrator import stage_defs, compute_status
from blockchain.multiactor_backend import MultiActorBackend

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]

SERVICE_URLS = {
    "cleaning": os.getenv("CLEANING_URL", "http://localhost:8001"),
    "training": os.getenv("TRAINING_URL", "http://localhost:8002"),
    "model":    os.getenv("REVIEW_URL",   "http://localhost:8003"),
}

# Known identities (for the UI to match against). Addresses are public.
ADMIN_ADDRESS = "0x5d1a7e1b7dC23d2E1f677E1Ed919fb501D36205e"
ACTORS = {
    "cleaning": {"role": "DATA_CLEANER",  "address": "0x73296D211A805362803aeCc9d181DF2585AfCA6F"},
    "training": {"role": "MODEL_TRAINER", "address": "0x83EF06a12F91A3a9a78C637E1dcb1034df67b966"},
    "model":    {"role": "REVIEWER",      "address": "0xf59622D37998AF8087EAfD16E4271dFB80A4DdB9"},
}

app = FastAPI(title="Pipeline Orchestrator")

# Allow the static frontend (any origin) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "orchestrator", "services": SERVICE_URLS}


@app.get("/actors")
def actors():
    return {"admin": ADMIN_ADDRESS, "actors": ACTORS}


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


@app.post("/pipeline/create")
def create_pipeline():
    """ADMIN: create a fresh pipeline and grant the three actor roles."""
    result = subprocess.run(
        [sys.executable, "src/setup_pipeline_roles.py"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={
            "error": "pipeline setup failed",
            "log": result.stdout, "stderr_tail": result.stderr[-1500:]})
    match = re.search(r"Pipeline (\d+) is set up", result.stdout) or \
        re.search(r"id = (\d+)", result.stdout)
    return {
        "pipeline_id": int(match.group(1)) if match else None,
        "log": result.stdout,
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
            "log": result.stdout, "stderr_tail": result.stderr[-1500:]})
    return {"stage": "root(dataset+environment)", "status": "certified",
            "by": "admin", "log": result.stdout}


@app.post("/pipeline/{pipeline_id}/certify-roots")
def certify_roots_endpoint(pipeline_id: int):
    return _certify_roots(pipeline_id)


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
        "log": body.get("log"),
    }


@app.post("/pipeline/{pipeline_id}/run/{stage}")
def run_stage_endpoint(pipeline_id: int, stage: str):
    """Run a single actor stage (cleaning / training / model)."""
    if stage not in SERVICE_URLS:
        raise HTTPException(status_code=400, detail={"error": f"unknown stage '{stage}'"})
    return _call_service(stage, pipeline_id)


@app.post("/run-all/{pipeline_id}")
def run_all(pipeline_id: int):
    """Drive the whole workflow: admin roots, then the three actor services."""
    results = [_certify_roots(pipeline_id)]
    for stage in ("cleaning", "training", "model"):
        results.append(_call_service(stage, pipeline_id))
    return {"pipeline_id": pipeline_id, "status": "complete", "steps": results}