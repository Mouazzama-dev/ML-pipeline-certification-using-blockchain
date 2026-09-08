"""
storage.py
----------
MinIO object storage wrapper for the pipeline.

This is the ONLY file that talks to MinIO. All other services import
from here. If the storage backend changes, only this file needs updating.

Connection is configured via environment variables (defaults work for
the local docker-compose.minio.yml setup):

  MINIO_ENDPOINT    host:port      (default: localhost:9000)
  MINIO_ACCESS_KEY  access key     (default: minioadmin)
  MINIO_SECRET_KEY  secret key     (default: minioadmin)
  MINIO_SECURE      "true" for TLS (default: false)

Bucket names are declared as constants here so every service
references the same string — no magic strings elsewhere.
"""

import hashlib
import os
import tempfile
from pathlib import Path

from minio import Minio
from minio.error import S3Error


# ── Bucket names — single source of truth ────────────────────────────────────

BUCKET_RAW_DATASETS  = "raw-datasets"    # raw files uploaded by admin
BUCKET_STAGE_OUTPUTS = "stage-outputs"   # outputs produced by each stage run
BUCKET_RUN_LOGS      = "run-logs"        # stdout/stderr from container runs

ALL_BUCKETS = [BUCKET_RAW_DATASETS, BUCKET_STAGE_OUTPUTS, BUCKET_RUN_LOGS]


# ── MinIO client ──────────────────────────────────────────────────────────────

def _client() -> Minio:
    # Internal helper — callers use the public functions below, not this.
    return Minio(
        endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
    )


def ensure_buckets() -> None:
    """Create all required buckets if they do not already exist.

    Call this once at application startup (e.g. in orchestrator_api.py's
    lifespan handler). Safe to call multiple times — skips existing buckets.
    """
    client = _client()
    for name in ALL_BUCKETS:
        if not client.bucket_exists(name):
            client.make_bucket(name)


# ── Core operations ───────────────────────────────────────────────────────────

def compute_hash(file_path: str | Path) -> str:
    """Return the SHA-256 hex digest of a local file.

    Used in two places:
      - before upload, to know what hash to certify on-chain
      - after download, to verify the file matches the certified hash
    Reading in 64 KB chunks so large files do not load fully into memory.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def put(bucket: str, key: str, file_path: str | Path) -> str:
    """Upload a local file to bucket/key.

    Computes the SHA-256 before uploading and stores it as object metadata
    so it can be retrieved quickly without re-downloading.

    Returns the SHA-256 hex digest so the caller can certify the file
    on-chain immediately — no separate hash step needed.
    """
    file_path = Path(file_path)
    sha256 = compute_hash(file_path)

    _client().fput_object(
        bucket_name=bucket,
        object_name=key,
        file_path=str(file_path),
        metadata={"x-amz-meta-sha256": sha256},
    )
    return sha256


def get(bucket: str, key: str, dest_path: str | Path) -> None:
    """Download bucket/key to dest_path.

    Creates parent directories automatically so callers do not need to
    mkdir before calling.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    _client().fget_object(bucket, key, str(dest_path))


def exists(bucket: str, key: str) -> bool:
    """Return True if bucket/key exists in MinIO, False if not found.

    Used by StageRunner to poll for container output — the runner keeps
    calling this until it returns True or the timeout expires.
    """
    try:
        _client().stat_object(bucket, key)
        return True
    except S3Error as e:
        if e.code == "NoSuchKey":
            return False
        raise  # unexpected error — propagate so it is not silently swallowed


def hash_remote(bucket: str, key: str) -> str:
    """Download bucket/key to a temp file, compute its SHA-256, delete the temp file.

    Used by StageRunner before running a gated stage: it pulls the parent
    stage's output from MinIO and recomputes the hash from actual bytes.
    This catches any silent replacement or corruption — we do NOT trust
    the metadata stored at upload time for this verification step.
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        get(bucket, key, tmp_path)
        return compute_hash(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)