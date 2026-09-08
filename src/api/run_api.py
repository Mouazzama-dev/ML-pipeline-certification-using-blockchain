"""
run_api.py
----------
HTTP endpoints that wrap StageRunner for the frontend.

Three routes — the same for every stage; stage_name is just a form field:
  POST /run/stage              accept uploaded files, start background run, return run_id
  GET  /run/{run_id}/status    poll: queued | running | success | failed
  GET  /run/{run_id}/result    fetch manifest + hashes when status = success

Run state is stored in memory (_RUNS dict). A server restart clears it —
acceptable for the thesis demo.
"""

import shutil
import tempfile
import uuid
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from services.stage_runner import StageConfig, StageResult, StageRunner

router = APIRouter(prefix="/run", tags=["stage-runner"])

# In-memory run store: run_id → {status, result, error}
_RUNS: dict[str, dict] = {}


# ── POST /run/stage ───────────────────────────────────────────────────────────

@router.post("/stage")
async def start_stage_run(
    pipeline_id:       str              = Form(...),
    stage_name:        str              = Form(...),
    is_root_stage:     str              = Form(...),   # "true" or "false"
    parent_output_key: str              = Form(""),
    parent_cert_hash:  str              = Form(""),
    code_file:         UploadFile       = File(...),
    requirements_file: UploadFile       = File(...),
    raw_input_file:    UploadFile | None = File(None),
):
    """Accept uploaded actor files and start a stage run in the background.

    Returns {run_id} immediately. Poll GET /run/{run_id}/status until
    status = "success" or "failed", then call GET /run/{run_id}/result.

    is_root_stage: "true" for dataset/environment, "false" for cleaning/training/model.
    """
    is_root = is_root_stage.strip().lower() in ("true", "1", "yes")

    run_id  = uuid.uuid4().hex
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"run-{run_id[:8]}-"))

    # Save uploaded files to temp dir — background thread cleans up when done.
    code_path = tmp_dir / "script.py"
    req_path  = tmp_dir / "requirements.txt"
    code_path.write_bytes(await code_file.read())
    req_path.write_bytes(await requirements_file.read())

    raw_input_path = None
    if raw_input_file is not None:
        raw_input_path = tmp_dir / (raw_input_file.filename or "input.csv")
        raw_input_path.write_bytes(await raw_input_file.read())

    config = StageConfig(
        stage_name=stage_name,
        pipeline_id=pipeline_id,
        code_file=code_path,
        requirements_file=req_path,
        is_root_stage=is_root,
        parent_output_key=parent_output_key,
        parent_cert_hash=parent_cert_hash,
        raw_input_file=raw_input_path,
    )

    _RUNS[run_id] = {"status": "queued", "result": None, "error": ""}
    Thread(target=_run_stage, args=(run_id, config, tmp_dir), daemon=True).start()

    return {"run_id": run_id}


def _run_stage(run_id: str, config: StageConfig, tmp_dir: Path) -> None:
    """Background thread: call StageRunner and store the result in _RUNS."""
    _RUNS[run_id]["status"] = "running"
    try:
        result = StageRunner().run(config)
        _RUNS[run_id]["status"] = result.status  # "success" or "failed"
        _RUNS[run_id]["result"] = result
        if result.status == "failed":
            _RUNS[run_id]["error"] = result.error
    except ValueError as e:
        # Chain integrity failure (hash mismatch) — hard abort.
        _RUNS[run_id]["status"] = "failed"
        _RUNS[run_id]["error"]  = str(e)
    except Exception as e:
        _RUNS[run_id]["status"] = "failed"
        _RUNS[run_id]["error"]  = f"Unexpected error: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── GET /run/{run_id}/status ──────────────────────────────────────────────────

@router.get("/{run_id}/status")
def get_run_status(run_id: str):
    """Return the current status of a run.

    status values:
      queued   — accepted, background thread not started yet
      running  — StageRunner is executing
      success  — completed, call /result to get the manifest
      failed   — container error, hash mismatch, or timeout; error field is set
    """
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id!r}")
    return {"run_id": run_id, "status": run["status"], "error": run["error"]}


# ── GET /run/{run_id}/result ──────────────────────────────────────────────────

@router.get("/{run_id}/result")
def get_run_result(run_id: str):
    """Return the manifest and hashes for a completed run.

    Only available when status = "success".
    The frontend passes manifest_hash and parents to storeCertificate via MetaMask.
    """
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id!r}")

    if run["status"] != "success":
        raise HTTPException(
            status_code=409,
            detail=f"Run not complete (status={run['status']!r}). "
                   f"Poll /run/{run_id}/status first.",
        )

    r: StageResult = run["result"]
    return {
        "run_id":           run_id,
        "manifest_hash":    r.manifest_hash,
        "manifest_dict":    r.manifest_dict,
        "output_hash":      r.output_hash,
        "container_digest": r.container_digest,
        "output_minio_key": r.output_minio_key,
        "logs_minio_key":   r.logs_minio_key,
        "parents":          r.parents,
    }