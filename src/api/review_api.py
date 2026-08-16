#!/usr/bin/env python3
"""
Review / model microservice (Person C / REVIEWER) -- HTTP wrapper.

Holds ONLY Person C's key (PERSON_C_PRIVATE_KEY). Wraps review_service.py,
which does the full-chain audit then certifies (approves) the model stage.

Run locally (from repo root):
    uvicorn api.review_api:app --app-dir src --port 8003
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

STAGE = "model"
SERVICE_SCRIPT = "src/services/review_service.py"
RECEIPT_PATH = "certificates/receipts/ma_model_receipt.json"
ACTOR_KEY_ENV = "PERSON_C_PRIVATE_KEY"

app = FastAPI(title="Review Service (Person C / REVIEWER)")


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
    return {
        "status": "ok",
        "service": STAGE,
        "role": "REVIEWER",
        "actor": actor_address(),
    }


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
            "stdout_tail": result.stdout[-1500:],
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
        "receipt": receipt,
    }