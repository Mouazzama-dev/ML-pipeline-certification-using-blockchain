"""
tests/test_run_api.py
---------------------
Phase 3 smoke test for api/run_api.py.

Uses FastAPI TestClient — no running server needed.

Three checks:
  1. POST /run/stage     → run_id returned immediately
  2. GET  /run/{id}/status → polls until success or failed
  3. GET  /run/{id}/result → manifest_hash, output_hash, parents verified

Run from repo root:
    pip install httpx
    python tests/test_run_api.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.run_api import router as run_router
from services.storage import ensure_buckets

app = FastAPI()
app.include_router(run_router)
client = TestClient(app)

INPUT_FILE = Path("data/raw/IRIS.csv")

SCRIPT = """\
import os, shutil
shutil.copy(os.environ["INPUT_FILE"],
            os.path.join(os.environ["OUTPUT_DIR"], "output.csv"))
print("done")
"""


def main():
    print("Phase 3 — run_api.py smoke test")
    print("=" * 45)

    ensure_buckets()

    if not INPUT_FILE.exists():
        sys.exit(f"ERROR: {INPUT_FILE} not found")

    # ── Step 1: POST /run/stage ───────────────────────────────────────────────
    print("  [1/3] POST /run/stage ...", end=" ", flush=True)

    resp = client.post(
        "/run/stage",
        data={
            "pipeline_id":   "api-test",
            "stage_name":    "dataset",
            "is_root_stage": "true",
        },
        files={
            "code_file":         ("script.py",        SCRIPT.encode(), "text/plain"),
            "requirements_file": ("requirements.txt",  b"",            "text/plain"),
            "raw_input_file":    ("IRIS.csv", INPUT_FILE.read_bytes(), "text/csv"),
        },
    )

    assert resp.status_code == 200, f"FAIL {resp.status_code}: {resp.text}"
    run_id = resp.json()["run_id"]
    assert run_id
    print(f"OK  (run_id={run_id[:8]}...)")

    # ── Step 2: Poll /status ──────────────────────────────────────────────────
    print("  [2/3] Polling /status ...", end=" ", flush=True)

    status = "queued"
    for _ in range(60):   # up to 5 minutes
        r = client.get(f"/run/{run_id}/status")
        assert r.status_code == 200
        status = r.json()["status"]
        if status in ("success", "failed"):
            break
        time.sleep(5)

    assert status == "success", \
        f"Run ended with status={status!r}: {client.get(f'/run/{run_id}/status').json()['error']}"
    print(f"OK  (status={status})")

    # ── Step 3: GET /result ───────────────────────────────────────────────────
    print("  [3/3] GET /result ...", end=" ", flush=True)

    r = client.get(f"/run/{run_id}/result")
    assert r.status_code == 200, f"FAIL {r.status_code}: {r.text}"
    body = r.json()

    assert body["manifest_hash"],                              "manifest_hash missing"
    assert body["output_hash"],                                "output_hash missing"
    assert body["container_digest"],                           "container_digest missing"
    assert body["parents"] == [],                              "root stage must have no parents"
    assert body["manifest_dict"]["stage_name"] == "dataset",   "wrong stage_name in manifest"
    print("OK")

    print(f"         manifest_hash    : {body['manifest_hash']}")
    print(f"         output_hash      : {body['output_hash']}")
    print(f"         container_digest : {body['container_digest'][:28]}...")
    print(f"         parents          : {body['parents']}")

    print()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()