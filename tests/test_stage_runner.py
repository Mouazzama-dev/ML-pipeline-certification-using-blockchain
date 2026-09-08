"""
tests/test_stage_runner.py
--------------------------
Phase 2 smoke test for services/stage_runner.py.

Three scenarios:
  1. Root stage   — raw file input, manifest produced, no parents
  2. Gated stage  — parent output pulled from MinIO, hash verified, chained
  3. Tamper test  — wrong parent_cert_hash must raise ValueError (hard abort)

Requirements:
  - Phase 0 and 1 passing (MinIO + Docker running)

Run from repo root:
    python tests/test_stage_runner.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.storage import ensure_buckets
from services.stage_runner import StageConfig, StageRunner

INPUT_FILE = Path("data/raw/IRIS.csv")

# Minimal passthrough script — copies INPUT_FILE to OUTPUT_DIR/output.csv.
SCRIPT = """\
import os, shutil
shutil.copy(os.environ["INPUT_FILE"],
            os.path.join(os.environ["OUTPUT_DIR"], "output.csv"))
print("done")
"""


def tmp_files():
    """Write the actor script and empty requirements to temp files."""
    c = tempfile.NamedTemporaryFile(mode="w", suffix=".py",  delete=False)
    c.write(SCRIPT); c.flush()
    r = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    r.write("");      r.flush()
    return Path(c.name), Path(r.name)


def main():
    print("Phase 2 — stage_runner.py smoke test")
    print("=" * 45)

    ensure_buckets()

    if not INPUT_FILE.exists():
        sys.exit(f"ERROR: {INPUT_FILE} not found")

    runner            = StageRunner()
    code_file, req_file = tmp_files()

    try:
        # ── Test 1: Root stage ────────────────────────────────────────────────
        print("  [1/3] Root stage (dataset) ...", end=" ", flush=True)

        root = runner.run(StageConfig(
            stage_name="dataset",
            pipeline_id="smoke-test",
            code_file=code_file,
            requirements_file=req_file,
            is_root_stage=True,
            raw_input_file=INPUT_FILE,
        ))

        assert root.status  == "success", f"FAIL: {root.error}"
        assert root.parents == [],        "Root stage should have no parents"
        assert root.manifest_hash,        "Manifest hash is empty"
        print("OK")
        print(f"         manifest hash    : {root.manifest_hash}")
        print(f"         output hash      : {root.output_hash}")
        print(f"         container digest : {root.container_digest[:24]}...")

        # ── Test 2: Gated stage chained from root ─────────────────────────────
        print("  [2/3] Gated stage (cleaning ← dataset) ...", end=" ", flush=True)

        gated = runner.run(StageConfig(
            stage_name="cleaning",
            pipeline_id="smoke-test",
            code_file=code_file,
            requirements_file=req_file,
            is_root_stage=False,
            parent_output_key=root.output_minio_key,
            parent_cert_hash=root.output_hash,
        ))

        assert gated.status  == "success",              f"FAIL: {gated.error}"
        assert gated.parents == [root.output_hash],     "Parent hash missing from manifest"
        assert gated.manifest_hash,                     "Manifest hash is empty"
        print("OK")
        print(f"         manifest hash    : {gated.manifest_hash}")
        print(f"         parent verified  : {root.output_hash[:24]}...")

        # ── Test 3: Wrong parent hash must abort before building ──────────────
        print("  [3/3] Tamper detection (bad parent_cert_hash) ...", end=" ", flush=True)

        try:
            runner.run(StageConfig(
                stage_name="training",
                pipeline_id="smoke-test",
                code_file=code_file,
                requirements_file=req_file,
                is_root_stage=False,
                parent_output_key=gated.output_minio_key,
                parent_cert_hash="0" * 64,   # wrong hash
            ))
            assert False, "Expected ValueError — none raised"
        except ValueError as e:
            assert "mismatch" in str(e).lower()
        print("OK  (ValueError raised as expected)")

    finally:
        code_file.unlink(missing_ok=True)
        req_file.unlink(missing_ok=True)

    print()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()