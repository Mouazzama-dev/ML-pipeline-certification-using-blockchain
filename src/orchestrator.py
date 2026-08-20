#!/usr/bin/env python3
"""
Orchestrator for the multi-actor certification pipeline (off-chain driver).

The workflow's "brain": it derives each stage's status from the V2 registry
(on-chain) and drives the next runnable stage's service. No new contract --
status is a pure function of what is certified on-chain, so it can never drift
from reality.

  Stage DAG:  dataset ─┐
                       ├─→ cleaning ─→ training ─→ model
              environment ─┘        (env also ─┘)

  Status per stage:
    CERTIFIED  - this stage's cert exists on V2
    READY      - all parents CERTIFIED, this one not yet (can run now)
    LOCKED     - some parent not CERTIFIED yet (cannot run)

Usage:
    python src/orchestrator.py --pipeline-id 1 --status     # just show the table
    python src/orchestrator.py --pipeline-id 1 --run-next   # run the next READY stage
    python src/orchestrator.py --pipeline-id 1 --run-all    # drive the whole workflow

Reads from .env: POLYGON_RPC_URL, ROLE_MANAGER_ADDRESS, POLYGON_CONTRACT_ADDRESS_V2,
and the PERSON_*_PRIVATE_KEY needed by whichever stage service it runs.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Make src/ importable no matter where this is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

from blockchain.multiactor_backend import MultiActorBackend

PY = sys.executable

ADMIN = "0x5d1a7e1b7dC23d2E1f677E1Ed919fb501D36205e"
PERSON_A = "0x73296D211A805362803aeCc9d181DF2585AfCA6F"
PERSON_B = "0x83EF06a12F91A3a9a78C637E1dcb1034df67b966"
PERSON_C = "0xf59622D37998AF8087EAfD16E4271dFB80A4DdB9"


def stage_defs(pid: int) -> list:
    """The pipeline DAG: each stage, its parents, its assigned actor, the
    receipt that proves it, and the command that certifies it."""
    return [
        {"name": "dataset", "parents": [], "who": "admin", "actor": ADMIN,
         "receipt": "certificates/receipts/ma_dataset_receipt.json",
         "run": [PY, "src/certify_root_on_v2.py", "--pipeline-id", str(pid)]},
        {"name": "environment", "parents": [], "who": "admin", "actor": ADMIN,
         "receipt": "certificates/receipts/ma_environment_v1_receipt.json",
         "run": [PY, "src/certify_root_on_v2.py", "--pipeline-id", str(pid)]},
        {"name": "cleaning", "parents": ["dataset", "environment"],
         "who": "Person A (DATA_CLEANER)", "actor": PERSON_A,
         "receipt": "certificates/receipts/ma_cleaning_receipt.json",
         "run": [PY, "src/services/cleaning_service.py", "--pipeline-id", str(pid)]},
        {"name": "training", "parents": ["cleaning", "environment"],
         "who": "Person B (MODEL_TRAINER)", "actor": PERSON_B,
         "receipt": "certificates/receipts/ma_training_receipt.json",
         "run": [PY, "src/services/training_service.py", "--pipeline-id", str(pid)]},
        {"name": "model", "parents": ["training"],
         "who": "Person C (REVIEWER)", "actor": PERSON_C,
         "receipt": "certificates/receipts/ma_model_receipt.json",
         "run": [PY, "src/services/review_service.py", "--pipeline-id", str(pid)]},
    ]


def is_cert(backend, receipt_path: str) -> bool:
    """A stage is certified iff its receipt exists AND its hash is on V2."""
    p = Path(receipt_path)
    if not p.exists():
        return False
    try:
        h = json.loads(p.read_text())["manifest_sha256"]
    except Exception:
        return False
    return backend.is_certified(h)


def compute_status(backend, stages: list) -> dict:
    cert = {s["name"]: is_cert(backend, s["receipt"]) for s in stages}
    status = {}
    for s in stages:
        if cert[s["name"]]:
            status[s["name"]] = "CERTIFIED"
        elif all(cert[p] for p in s["parents"]):
            status[s["name"]] = "READY"
        else:
            status[s["name"]] = "LOCKED"
    return status


def print_status(backend, stages: list, status: dict) -> None:
    print(f"{'STAGE':13} {'STATUS':10} {'AUTH':6} {'ASSIGNED TO'}")
    print("-" * 60)
    for s in stages:
        # AUTH = does the assigned actor actually have on-chain permission?
        try:
            auth = "OK" if backend.can_certify(s["name"], s["actor"]) else "NO"
        except Exception:
            auth = "?"
        print(f"{s['name']:13} {status[s['name']]:10} {auth:6} {s['who']}")


def run_stage(s: dict) -> bool:
    print(f"\n>>> Running stage '{s['name']}'  ({s['who']}) ...")
    result = subprocess.run(s["run"])
    if result.returncode != 0:
        print(
            f"\n!!! Stage '{s['name']}' REJECTED/failed (exit {result.returncode}).\n"
            f"    Recovery path: stage stays OPEN -- fix the cause (role/gas/parent) "
            f"and re-run. Nothing downstream can proceed until it certifies.",
            file=sys.stderr,
        )
        return False
    return True


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Multi-actor pipeline orchestrator.")
    ap.add_argument("--pipeline-id", type=int, default=int(os.getenv("PIPELINE_ID", "0")))
    ap.add_argument("--status", action="store_true", help="show the status table and exit")
    ap.add_argument("--run-next", action="store_true", help="run the next READY stage")
    ap.add_argument("--run-all", action="store_true", help="drive the whole workflow")
    args = ap.parse_args()

    if not args.pipeline_id:
        print("PIPELINE_ID not set (use --pipeline-id or .env).", file=sys.stderr)
        sys.exit(1)

    backend = MultiActorBackend(pipeline_id=args.pipeline_id)
    stages = stage_defs(args.pipeline_id)

    print(f"=== Orchestrator | pipeline {args.pipeline_id} ===\n")
    status = compute_status(backend, stages)
    print_status(backend, stages, status)

    if args.run_next:
        nxt = next((s for s in stages if status[s["name"]] == "READY"), None)
        if not nxt:
            if all(status[s["name"]] == "CERTIFIED" for s in stages):
                print("\nAll stages CERTIFIED. Nothing to run.")
            else:
                print("\nNo READY stage (some are LOCKED). Check the table above.")
            return
        run_stage(nxt)
        print("\n--- Updated status ---")
        print_status(backend, stages, compute_status(backend, stages))

    elif args.run_all:
        while True:
            status = compute_status(backend, stages)
            if all(status[s["name"]] == "CERTIFIED" for s in stages):
                print("\nAll stages CERTIFIED. Pipeline complete.")
                break
            nxt = next((s for s in stages if status[s["name"]] == "READY"), None)
            if not nxt:
                print("\nStuck: no READY stage but not all certified "
                      "(a LOCKED stage's parent failed).", file=sys.stderr)
                break
            if not run_stage(nxt):
                print("\nStopping run-all (recovery path). Fix and re-run.",
                      file=sys.stderr)
                break
        print("\n--- Final status ---")
        print_status(backend, stages, compute_status(backend, stages))


if __name__ == "__main__":
    main()