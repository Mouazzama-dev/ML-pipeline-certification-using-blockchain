"""
stage_runner.py
---------------
The shared pipeline stage loop used by every stage.

All five stages (dataset, environment, cleaning, training, model) run through
the same six steps. Only the parameters in StageConfig differ per stage.

Six steps:
  1. Resolve input   — root stages use raw_input_file; gated stages pull
                       the parent's output from MinIO.
  2. Verify input    — gated stages only: recompute hash from MinIO bytes
                       and abort if it does not match parent_cert_hash.
  3. Build container — ContainerRunner.build()
  4. Run container   — ContainerRunner.run()
  5. Assemble manifest — all hashes, URIs, and parent links in one dict.
  6. Hash manifest   — SHA-256 of the canonical JSON → this goes on-chain.

Public API:
  config = StageConfig(...)
  result = StageRunner().run(config)
"""

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from services.container_runner import ContainerRunner
from services.storage import BUCKET_STAGE_OUTPUTS, get
from services.verification import verify_remote


# ── Config and result types ───────────────────────────────────────────────────

@dataclass
class StageConfig:
    """Everything that differs between stages. The loop itself is always the same."""

    stage_name:        str        # "dataset" | "environment" | "cleaning" | "training" | "model"
    pipeline_id:       str | int
    code_file:         Path       # actor's Python script
    requirements_file: Path       # actor's requirements.txt
    is_root_stage:     bool       # True for dataset/environment — no parent to verify

    # Gated stages (is_root_stage=False) must set both of these:
    parent_output_key: str = ""   # MinIO key of the parent's output file
    parent_cert_hash:  str = ""   # on-chain certified hash of the parent's output

    # Root stages (is_root_stage=True) must set this:
    raw_input_file: Path | None = None  # the raw file passed into the container

    timeout_seconds: int = 300    # container run timeout


@dataclass
class StageResult:
    """Everything the frontend needs to call storeCertificate on-chain."""

    status:           str         # "success" or "failed"
    manifest_hash:    str         # SHA-256 of manifest_dict → certify this on-chain
    manifest_dict:    dict        # full manifest for audit and display
    output_hash:      str         # SHA-256 of the output file in MinIO
    container_digest: str         # docker image digest → proves which code ran
    output_minio_key: str         # stage-outputs/pipeline_X/stage/output.csv
    logs_minio_key:   str         # run-logs/pipeline_X/stage/run.log
    parents:          list        # parent cert hashes passed to storeCertificate
    error:            str = ""    # non-empty only on failure


# ── Manifest hashing ──────────────────────────────────────────────────────────

def _hash_manifest(manifest_dict: dict) -> str:
    """Return SHA-256 of the manifest serialized as canonical JSON.

    Canonical = keys sorted alphabetically, no extra whitespace.
    This guarantees the same manifest always produces the same hash
    regardless of the order keys were inserted.
    """
    canonical = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Stage runner ──────────────────────────────────────────────────────────────

class StageRunner:
    """Runs any pipeline stage through the six-step loop."""

    def run(self, config: StageConfig) -> StageResult:
        """Execute the stage and return a StageResult.

        Raises ValueError for chain integrity failures (step 2 hash mismatch).
        All other failures (container crash, timeout, no output) are returned
        as StageResult(status="failed") so the API can surface them cleanly.
        """
        work_dir = Path(tempfile.mkdtemp(prefix="stage-runner-"))
        runner   = ContainerRunner()

        try:
            # ── Step 1: Resolve input ─────────────────────────────────────────
            if config.is_root_stage:
                if config.raw_input_file is None:
                    raise ValueError("is_root_stage=True but raw_input_file is not set")
                input_file = Path(config.raw_input_file)
                parents    = []

            else:
                if not config.parent_output_key or not config.parent_cert_hash:
                    raise ValueError(
                        "is_root_stage=False but parent_output_key or "
                        "parent_cert_hash is not set"
                    )

                # ── Step 2: Verify input hash (gated stages only) ─────────────
                # Downloads from MinIO and recomputes from actual bytes.
                # Raises ValueError if the file does not match the certified hash.
                verify_remote(
                    bucket=BUCKET_STAGE_OUTPUTS,
                    key=config.parent_output_key,
                    expected_hex=config.parent_cert_hash,
                    context=f"{config.stage_name} ← {config.parent_output_key}",
                )

                # Download the verified file so ContainerRunner can bake it in.
                suffix     = Path(config.parent_output_key).suffix
                input_file = work_dir / f"input{suffix}"
                get(BUCKET_STAGE_OUTPUTS, config.parent_output_key, input_file)
                parents = [config.parent_cert_hash]

            # ── Step 3: Build container ───────────────────────────────────────
            build = runner.build(
                code_file=config.code_file,
                requirements_file=config.requirements_file,
                input_file=input_file,
                stage_name=config.stage_name,
                pipeline_id=config.pipeline_id,
            )

            # ── Step 4: Run container ─────────────────────────────────────────
            # ContainerRunner.run() blocks until the container exits or times out,
            # then uploads output + logs to MinIO and returns RunResult.
            run_result = runner.run(
                build=build,
                stage_name=config.stage_name,
                pipeline_id=config.pipeline_id,
                timeout=config.timeout_seconds,
            )

            if run_result.status != "success":
                return StageResult(
                    status="failed",
                    manifest_hash="",
                    manifest_dict={},
                    output_hash="",
                    container_digest=build.image_digest,
                    output_minio_key="",
                    logs_minio_key=run_result.logs_minio_key,
                    parents=parents,
                    error=f"Container exited {run_result.exit_code}",
                )

            # ── Steps 5+6: Assemble manifest and compute its hash ─────────────
            manifest_dict = {
                "schema_version":     "2.0",
                "stage_name":         config.stage_name,
                "pipeline_id":        str(config.pipeline_id),
                "timestamp":          datetime.now(timezone.utc).isoformat(),
                # What went into the container
                "input_hash":         build.input_hash,
                "code_hash":          build.code_hash,
                "requirements_hash":  build.requirements_hash,
                # Which container ran
                "container_digest":   build.image_digest,
                # What came out
                "output_hash":        run_result.output_hash,
                "output_storage_uri": (
                    f"minio://{BUCKET_STAGE_OUTPUTS}/{run_result.output_minio_key}"
                ),
                "logs_storage_uri": (
                    f"minio://run-logs/{run_result.logs_minio_key}"
                ),
                # Chain links
                "parents":            parents,
            }

            manifest_hash = _hash_manifest(manifest_dict)

            return StageResult(
                status="success",
                manifest_hash=manifest_hash,
                manifest_dict=manifest_dict,
                output_hash=run_result.output_hash,
                container_digest=build.image_digest,
                output_minio_key=run_result.output_minio_key,
                logs_minio_key=run_result.logs_minio_key,
                parents=parents,
            )

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)