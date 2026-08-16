#!/usr/bin/env python3
"""
Cleaning microservice (Person A / DATA_CLEANER) -- HTTP wrapper.

Holds ONLY Person A's key (PERSON_A_PRIVATE_KEY). Wraps cleaning_service.py.

Endpoints:
    GET  /health          -> liveness + which actor this service signs as
    POST /run             -> run the cleaning stage; return receipt + full log

Run locally (from repo root):
    uvicorn api.cleaning_api:app --app-dir src --port 8001
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]

STAGE = "cleaning"
SERVICE_SCRIPT = "src/services/cleaning_service.py"
RECEIPT_PATH = "certificates/receipts/ma_cleaning_receipt.json"
ACTOR_KEY_ENV = "PERSON_A_PRIVATE_KEY"

app = FastAPI(title="Cleaning Service (Person A / DATA_CLEANER)")


class RunRequest(BaseModel):
    pipeline_id: int


def actor_address():
    key = os.getenv(ACTOR_KEY_ENV)
    if not key:
        return None
    from web3 import Web3
    return Web3().eth.account.from_key(key).address


@app.get("/health")
def health():
    return {"status": "ok", "service": STAGE, "role": "DATA_CLEANER",
            "actor": actor_address()}


@app.post("/run")
def run(req: RunRequest):
    result = subprocess.run(
        [sys.executable, SERVICE_SCRIPT, "--pipeline-id", str(req.pipeline_id)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail={
            "stage": STAGE,
            "error": "stage rejected or failed",
            "exit_code": result.returncode,
            "log": result.stdout,
            "stderr_tail": result.stderr[-1500:],
        })

    receipt = json.loads((REPO_ROOT / RECEIPT_PATH).read_text())
    return {
        "stage": STAGE,
        "status": "certified",
        "pipeline_id": req.pipeline_id,
        "actor_address": receipt.get("actor_address"),
        "tx_id": receipt.get("tx_id"),
        "block_id": receipt.get("block_id"),
        "manifest_sha256": receipt.get("manifest_sha256"),
        "log": result.stdout,          # full step-by-step detail
        "receipt": receipt,
    }