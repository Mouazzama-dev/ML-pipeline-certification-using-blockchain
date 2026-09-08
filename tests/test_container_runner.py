"""
tests/test_container_runner.py
------------------------------
Phase 1 smoke test for services/container_runner.py.

What it checks:
  1. build()  — Docker image builds, image digest is captured
  2. run()    — container runs sandboxed, exit code 0
  3. output   — output file exists in MinIO, hash matches

Requirements:
  - Phase 0 passed (MinIO running)
  - Docker daemon running  →  verify with: docker info

Run from repo root:
    python tests/test_container_runner.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from services.storage import ensure_buckets, exists, hash_remote, BUCKET_STAGE_OUTPUTS
from services.container_runner import ContainerRunner


# Minimal actor script: reads INPUT_FILE, copies it to OUTPUT_DIR/output.csv.
# No third-party libraries needed — proves the runner works before adding pandas etc.
ACTOR_SCRIPT = """\
import os, shutil

input_file = os.environ["INPUT_FILE"]
output_dir = os.environ["OUTPUT_DIR"]

output_path = os.path.join(output_dir, "output.csv")
shutil.copy(input_file, output_path)
print(f"Copied {input_file} -> {output_path}")
"""

PIPELINE_ID = "test"
STAGE_NAME  = "cleaning"
INPUT_FILE  = Path("data/raw/IRIS.csv")   # already in the repo


def check_docker():
    result = subprocess.run(["docker", "info"], capture_output=True)
    if result.returncode != 0:
        sys.exit("ERROR: Docker is not running. Start Docker and retry.")


def main():
    print("Phase 1 — container_runner.py smoke test")
    print("=" * 45)

    check_docker()
    ensure_buckets()

    if not INPUT_FILE.exists():
        sys.exit(f"ERROR: input file not found: {INPUT_FILE}")

    runner = ContainerRunner()

    # Write the actor script and an empty requirements.txt to temp files.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",  delete=False) as f:
        f.write(ACTOR_SCRIPT)
        code_file = Path(f.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("")   # no extra packages
        req_file = Path(f.name)

    try:
        # Step 1: build
        print("  [1/3] docker build ...   ", end="", flush=True)
        build = runner.build(
            code_file=code_file,
            requirements_file=req_file,
            input_file=INPUT_FILE,
            stage_name=STAGE_NAME,
            pipeline_id=PIPELINE_ID,
        )
        print("OK")
        print(f"         image digest : {build.image_digest}")
        print(f"         code hash    : {build.code_hash}")
        print(f"         input hash   : {build.input_hash}")

        # Step 2: run
        print("  [2/3] docker run  ...    ", end="", flush=True)
        result = runner.run(build, stage_name=STAGE_NAME, pipeline_id=PIPELINE_ID)
        print(f"OK  (exit {result.exit_code})")
        print(f"         status       : {result.status}")
        print(f"         output key   : {result.output_minio_key}")
        print(f"         output hash  : {result.output_hash}")
        print(f"         logs key     : {result.logs_minio_key}")

        assert result.status == "success", \
            f"Container failed — logs at MinIO:{result.logs_minio_key}"

        # Step 3: verify output in MinIO
        print("  [3/3] verifying MinIO ... ", end="", flush=True)
        assert exists(BUCKET_STAGE_OUTPUTS, result.output_minio_key), \
            "Output not found in MinIO"
        remote_hash = hash_remote(BUCKET_STAGE_OUTPUTS, result.output_minio_key)
        assert remote_hash == result.output_hash, \
            f"Output hash mismatch: {remote_hash} != {result.output_hash}"
        print("OK")

    finally:
        code_file.unlink(missing_ok=True)
        req_file.unlink(missing_ok=True)

    print()
    print("ALL TESTS PASSED")
    print(f"  Container digest : {build.image_digest}")
    print(f"  Output in MinIO  : stage-outputs/{result.output_minio_key}")


if __name__ == "__main__":
    main()