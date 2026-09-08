"""
tests/test_storage.py
---------------------
Phase 0 smoke test for services/storage.py.

Run from the repo root:
    pip install minio
    docker compose -f docker-compose.minio.yml up -d
    python tests/test_storage.py

All five lines should print OK. Final line: "ALL TESTS PASSED".
"""

import sys
import tempfile
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.storage import (
    ensure_buckets,
    compute_hash,
    put, get, exists, hash_remote,
    BUCKET_STAGE_OUTPUTS,
)

# A small deterministic file used for every test step.
TEST_CONTENT = b"Phase 0 storage test.\n"
TEST_KEY     = "test/phase0_smoke.txt"


def main():
    print("Phase 0 — storage.py smoke test")
    print("=" * 40)

    # Step 1: create buckets
    print("  [1/5] ensure_buckets()    ", end="", flush=True)
    ensure_buckets()
    print("OK")

    # Step 2: upload a file, check returned hash
    print("  [2/5] put()               ", end="", flush=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(TEST_CONTENT)
        local_path = Path(f.name)

    local_hash    = compute_hash(local_path)
    returned_hash = put(BUCKET_STAGE_OUTPUTS, TEST_KEY, local_path)
    assert returned_hash == local_hash, f"FAIL — hash mismatch: {returned_hash}"
    print("OK")

    # Step 3: existence check
    print("  [3/5] exists()            ", end="", flush=True)
    assert     exists(BUCKET_STAGE_OUTPUTS, TEST_KEY),            "FAIL — uploaded file not found"
    assert not exists(BUCKET_STAGE_OUTPUTS, "test/no_such.txt"),  "FAIL — phantom file found"
    print("OK")

    # Step 4: download and verify bytes
    print("  [4/5] get()               ", end="", flush=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        dl_path = Path(f.name)
    get(BUCKET_STAGE_OUTPUTS, TEST_KEY, dl_path)
    assert dl_path.read_bytes() == TEST_CONTENT, "FAIL — downloaded content differs"
    print("OK")

    # Step 5: hash_remote recomputes correctly from MinIO bytes
    print("  [5/5] hash_remote()       ", end="", flush=True)
    remote_hash = hash_remote(BUCKET_STAGE_OUTPUTS, TEST_KEY)
    assert remote_hash == local_hash, f"FAIL — remote hash mismatch: {remote_hash}"
    print("OK")

    print()
    print("ALL TESTS PASSED")
    print(f"  file SHA-256: {local_hash}")

    # Cleanup temp files (MinIO object stays — harmless)
    local_path.unlink(missing_ok=True)
    dl_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()