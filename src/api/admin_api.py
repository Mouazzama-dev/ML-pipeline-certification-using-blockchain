#!/usr/bin/env python3
"""
Admin support API (off-chain only).

The admin portal does all on-chain WRITES in the browser via MetaMask. This API
only provides the things the blockchain doesn't store:
  - pipeline names / descriptions            (display only)
  - actor display names                       (display only)
  - building dataset/environment manifests    -> returns the manifest SHA-256
    that the browser then certifies on-chain with storeCertificate.

No private keys and no signing here. CORS is enabled so the React app can call it.

Run locally (from repo root):
    uvicorn api.admin_api:app --app-dir src --port 8080
"""

import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]

# Off-chain display data lives here (names, descriptions, actor names).
STORE_PATH = REPO_ROOT / "certificates" / "pipelines.json"

app = FastAPI(title="Admin Support API (off-chain)")

# Allow the Vite dev server (and others) to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- store helpers
def _load_store() -> dict:
    if STORE_PATH.exists():
        return json.loads(STORE_PATH.read_text())
    return {"pipelines": {}, "actors": {}}


def _save_store(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, indent=2) + "\n")


# ----------------------------------------------------------------- models
class PipelineIn(BaseModel):
    id: int
    name: str
    description: str = ""


class ActorIn(BaseModel):
    address: str
    name: str
    role: str


class ManifestReq(BaseModel):
    pipeline_id: int
    dataset_path: str | None = None       # repo-relative; required for /manifest/dataset
    dependency_lock_path: str | None = None  # repo-relative; required for /manifest/environment


ADMIN_UPLOAD_ROOT = REPO_ROOT / "data" / "admin_uploads"


class StageHashIn(BaseModel):
    pipeline_id: int
    stage: str
    manifest_sha256: str
    tx_id: str = ""       # on-chain tx hash (for the receipt / parent refs)
    block_id: str = ""    # block number


# ----------------------------------------------------------------- health
@app.get("/health")
def health():
    return {"status": "ok", "service": "admin-support", "store": str(STORE_PATH.name)}


# ----------------------------------------------------------------- pipelines (names)
@app.get("/pipelines")
def list_pipelines():
    store = _load_store()
    return {"pipelines": store.get("pipelines", {})}


@app.get("/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: int):
    store = _load_store()
    p = store.get("pipelines", {}).get(str(pipeline_id))
    if not p:
        raise HTTPException(status_code=404, detail="pipeline not found (off-chain)")
    return p


@app.post("/pipelines")
def save_pipeline(p: PipelineIn):
    store = _load_store()
    store.setdefault("pipelines", {})[str(p.id)] = {
        "id": p.id, "name": p.name, "description": p.description,
    }
    _save_store(store)
    return {"saved": True, "pipeline": store["pipelines"][str(p.id)]}


# ----------------------------------------------------------------- actors (names)
@app.get("/actors/{pipeline_id}")
def list_actors(pipeline_id: int):
    store = _load_store()
    return {"actors": store.get("actors", {}).get(str(pipeline_id), [])}


@app.post("/actors/{pipeline_id}")
def save_actor(pipeline_id: int, a: ActorIn):
    store = _load_store()
    actors = store.setdefault("actors", {}).setdefault(str(pipeline_id), [])
    # replace if same address+role already present
    actors = [x for x in actors if not (x["address"].lower() == a.address.lower()
                                        and x["role"] == a.role)]
    actors.append({"address": a.address, "name": a.name, "role": a.role})
    store["actors"][str(pipeline_id)] = actors
    _save_store(store)
    return {"saved": True, "actors": actors}


# ----------------------------------------------------------------- manifest hashing
def _run(cmd: list) -> str:
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={
            "error": "manifest build failed",
            "log": result.stdout,
            "stderr_tail": result.stderr[-1500:],
        })
    return result.stdout


def _hash_of(path: str) -> str:
    """Compute the SHA-256 the same way the pipeline does (via hashing.py)."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from hashing import hash_file
    return hash_file(str(REPO_ROOT / path))


@app.post("/upload/admin/{pipeline_id}")
async def upload_admin_dataset(pipeline_id: int, files: list[UploadFile] = File(...)):
    """Admin uploads a dataset (or any root-stage files) for a given pipeline."""
    dest = ADMIN_UPLOAD_ROOT / f"pipeline_{pipeline_id}"
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        target = dest / f.filename
        content = await f.read()
        target.write_bytes(content)
        saved.append(str(target.relative_to(REPO_ROOT)))
    return {"pipeline_id": pipeline_id, "saved": saved}


@app.post("/manifest/dataset")
def build_dataset_manifest(req: ManifestReq):
    if not req.dataset_path:
        raise HTTPException(status_code=400, detail="dataset_path is required")
    full = REPO_ROOT / req.dataset_path
    if not full.exists():
        raise HTTPException(status_code=400, detail=f"dataset file not found: {req.dataset_path}")
    out = f"certificates/manifests/pipeline_{req.pipeline_id}_dataset_manifest.json"
    _run([sys.executable, "src/manifest_service.py",
          "--type", "dataset", "--output", out, "--overwrite",
          "--file", f"dataset={req.dataset_path}",
          "--meta", f"pipeline_id={req.pipeline_id}"])
    return {"stage": "dataset", "manifest_path": out,
            "manifest_sha256": "0x" + _hash_of(out)}


@app.post("/manifest/environment")
def build_environment_manifest(req: ManifestReq):
    if not req.dependency_lock_path:
        raise HTTPException(status_code=400, detail="dependency_lock_path is required")
    lock_full = REPO_ROOT / req.dependency_lock_path
    if not lock_full.exists():
        raise HTTPException(status_code=400, detail=f"dependency lock file not found: {req.dependency_lock_path}")
    snap_out = f"artifacts/environment/pipeline_{req.pipeline_id}_environment.json"
    _run([sys.executable, "src/environment_snapshot.py",
          "--label", f"pipeline-{req.pipeline_id}-env",
          "--dependency-lock", req.dependency_lock_path,
          "--output", snap_out, "--overwrite"])
    out = f"certificates/manifests/pipeline_{req.pipeline_id}_environment_manifest.json"
    _run([sys.executable, "src/manifest_service.py",
          "--type", "environment", "--output", out, "--overwrite",
          "--file", f"environment_snapshot={snap_out}",
          "--file", f"dependency_lock={req.dependency_lock_path}",
          "--meta", f"pipeline_id={req.pipeline_id}"])
    return {"stage": "environment", "manifest_path": out,
            "manifest_sha256": "0x" + _hash_of(out)}


# ----------------------------------------------------------------- stage hashes
@app.post("/stage-hash")
def save_stage_hash(h: StageHashIn):
    """
    Record a stage's manifest hash AND write a receipt file so later stages can
    reference it as a parent. Called by the UI right after it certifies a stage
    in MetaMask.
    """
    hh = h.manifest_sha256 if h.manifest_sha256.startswith("0x") else "0x" + h.manifest_sha256

    store = _load_store()
    hashes = store.setdefault("stage_hashes", {}).setdefault(str(h.pipeline_id), {})
    hashes[h.stage] = hh
    _save_store(store)

    # write a receipt file (fields required by manifest_service parent refs)
    receipts_dir = REPO_ROOT / "certificates" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "pipeline_id": h.pipeline_id,
        "stage": h.stage,
        "manifest_sha256": hh[2:] if hh.startswith("0x") else hh,  # bare hex
        "network": "polygon-amoy",
        "tx_id": h.tx_id,
        "block_id": h.block_id,
    }
    rpath = receipts_dir / f"ui_p{h.pipeline_id}_{h.stage}_receipt.json"
    rpath.write_text(json.dumps(receipt, indent=2) + "\n")

    return {"saved": True, "stage_hashes": hashes, "receipt": str(rpath.relative_to(REPO_ROOT))}


@app.get("/stage-hashes/{pipeline_id}")
def stage_hashes(pipeline_id: int):
    """
    Return the manifest hash per stage. Prefers hashes saved by the UI
    (POST /stage-hash), then falls back to reading saved receipt files.
    """
    # 1. UI-saved hashes take priority
    store = _load_store()
    saved = store.get("stage_hashes", {}).get(str(pipeline_id), {})

    receipts_dir = REPO_ROOT / "certificates" / "receipts"
    wanted = {
        "dataset": ["polygon_dataset_receipt.json", "dataset_receipt.json"],
        "environment": ["polygon_environment_v1_receipt.json", "environment_v1_receipt.json"],
        "cleaning": ["ma_cleaning_receipt.json", "polygon_cleaning_receipt.json"],
        "training": ["ma_training_receipt.json", "polygon_training_receipt.json"],
        "model": ["ma_model_receipt.json", "polygon_model_receipt.json"],
    }
    out = {}
    for stage, names in wanted.items():
        if stage in saved:
            out[stage] = saved[stage]
            continue
        out[stage] = None
        for n in names:
            p = receipts_dir / n
            if p.exists():
                data = json.loads(p.read_text())
                hh = data.get("manifest_sha256")
                out[stage] = ("0x" + hh) if hh and not hh.startswith("0x") else hh
                break
    return {"pipeline_id": pipeline_id, "stage_hashes": out}


# ============================================================================
# USER PORTAL — actor uploads output, backend builds structured manifest
# ============================================================================

# Stage graph: each stage's parents (must match the frontend config).
STAGE_PARENTS = {
    "dataset": [],
    "environment": [],
    "cleaning": ["dataset", "environment"],
    "training": ["cleaning", "environment"],
    "model": ["training"],
}

UPLOAD_ROOT = REPO_ROOT / "certificates" / "uploads"


@app.post("/upload/{pipeline_id}/{stage}")
async def upload_output(pipeline_id: int, stage: str, files: list[UploadFile] = File(...)):
    """
    Actor uploads their stage output file(s). Saved under
    certificates/uploads/pipeline_<id>/<stage>/. Returns saved paths
    (relative to repo root) for manifest building.
    """
    if stage not in STAGE_PARENTS:
        raise HTTPException(status_code=400, detail=f"unknown stage '{stage}'")
    dest = UPLOAD_ROOT / f"pipeline_{pipeline_id}" / stage
    dest.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        target = dest / f.filename
        content = await f.read()
        target.write_bytes(content)
        saved.append(str(target.relative_to(REPO_ROOT)))
    return {"pipeline_id": pipeline_id, "stage": stage, "saved": saved}


class StageManifestReq(BaseModel):
    pipeline_id: int
    stage: str
    files: list[str]          # repo-relative paths returned by /upload
    actor: str = ""           # actor wallet address (metadata only)


@app.post("/manifest/stage")
def build_stage_manifest(req: StageManifestReq):
    """
    Build a STRUCTURED manifest for an actor's stage output using
    manifest_service.py, wiring in the stage's parents (resolved from saved
    stage-hashes). Returns the manifest SHA-256 and parent hashes (bytes32[]).
    """
    if req.stage not in STAGE_PARENTS:
        raise HTTPException(status_code=400, detail=f"unknown stage '{req.stage}'")
    if not req.files:
        raise HTTPException(status_code=400, detail="no files provided")

    # resolve parents: hash (for on-chain) + receipt file path (for manifest_service)
    store = _load_store()
    saved = store.get("stage_hashes", {}).get(str(req.pipeline_id), {})
    receipts_dir = REPO_ROOT / "certificates" / "receipts"
    parent_hashes = []
    parent_args = []
    for p in STAGE_PARENTS[req.stage]:
        h = saved.get(p)
        if not h:
            raise HTTPException(status_code=400,
                                detail=f"parent '{p}' not certified yet for pipeline {req.pipeline_id}")
        parent_hashes.append(h)
        # manifest_service needs a receipt FILE (with network/tx_id/block_id/manifest_sha256)
        rpath = receipts_dir / f"ui_p{req.pipeline_id}_{p}_receipt.json"
        if not rpath.exists():
            raise HTTPException(status_code=400,
                                detail=f"parent receipt for '{p}' missing; re-certify that stage")
        parent_args += ["--parent", f"{p}={rpath.relative_to(REPO_ROOT)}"]

    # build --file args from uploaded files (name = filename stem)
    file_args = []
    for path in req.files:
        name = Path(path).stem
        file_args += ["--file", f"{name}={path}"]

    out = f"certificates/manifests/pipeline_{req.pipeline_id}_{req.stage}_manifest.json"
    _run([sys.executable, "src/manifest_service.py",
          "--type", req.stage, "--output", out, "--overwrite",
          *file_args, *parent_args,
          "--meta", f"pipeline_id={req.pipeline_id}",
          "--meta", f"stage={req.stage}",
          "--meta", f"actor={req.actor}"])

    return {
        "stage": req.stage,
        "manifest_path": out,
        "manifest_sha256": "0x" + _hash_of(out),
        "parents": parent_hashes,
    }