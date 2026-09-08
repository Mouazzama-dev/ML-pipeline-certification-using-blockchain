"""
verification.py
---------------
Hash verification utilities for inter-stage integrity checks.

StageRunner calls these before running any gated stage (cleaning, training,
model). The remote check downloads the parent stage's output from MinIO and
recomputes its SHA-256 from the actual bytes — it does NOT trust stored
metadata, so any silent replacement or corruption is caught.

Both functions raise ValueError on mismatch so the caller can treat it as
a hard abort — a mismatch means the chain is broken and the stage must not run.
"""

from pathlib import Path

from services.storage import compute_hash, hash_remote


def verify_local(file_path: str | Path, expected_hex: str, context: str = "") -> None:
    """Raise ValueError if the local file's SHA-256 does not match expected_hex.

    context is a label included in the error message (e.g. "cleaning input")
    to make failures easier to diagnose in logs.
    """
    actual = compute_hash(file_path)
    if actual != expected_hex:
        label = f" [{context}]" if context else ""
        raise ValueError(
            f"Hash mismatch{label}:\n"
            f"  expected : {expected_hex}\n"
            f"  actual   : {actual}\n"
            f"  file     : {file_path}"
        )


def verify_remote(bucket: str, key: str, expected_hex: str, context: str = "") -> None:
    """Raise ValueError if the MinIO object's recomputed SHA-256 does not match expected_hex.

    Downloads the object, recomputes from actual bytes (does not trust the
    metadata stored at upload time), and raises on mismatch. Used by
    StageRunner to verify parent stage outputs before running.
    """
    actual = hash_remote(bucket, key)
    if actual != expected_hex:
        label = f" [{context}]" if context else ""
        raise ValueError(
            f"Remote hash mismatch{label}:\n"
            f"  expected : {expected_hex}\n"
            f"  actual   : {actual}\n"
            f"  location : {bucket}/{key}"
        )