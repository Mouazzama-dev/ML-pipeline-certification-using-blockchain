"""
container_runner.py
-------------------
Builds a Docker image from actor code + requirements + input data, runs it in
a sandboxed container, and stores the output and logs in MinIO.

Every pipeline stage (cleaning, training, model) uses ContainerRunner.
No stage-specific logic lives here — the caller (StageRunner) passes what varies.

Sandbox constraints applied to every run:
  --network none    no outbound traffic during execution
  --memory 1g       RAM cap
  --cpus 1.5        CPU cap
  --user 1000:1000  non-root "runner" user (created in the Dockerfile)

Actor code contract (must be documented for actors):
  INPUT_FILE  env var → path to the input file inside the container
  OUTPUT_DIR  env var → directory to write output into
  The script must write exactly one file into OUTPUT_DIR.

Public API:
  runner = ContainerRunner()
  build  = runner.build(code_file, requirements_file, input_file, stage_name, pipeline_id)
  result = runner.run(build, stage_name, pipeline_id, timeout=300)
"""

import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from services.storage import (
    BUCKET_RUN_LOGS,
    BUCKET_STAGE_OUTPUTS,
    compute_hash,
    put,
)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class BuildResult:
    """Captured during docker build. Passed directly to run()."""
    image_tag:          str  # local docker tag e.g. pipeline-1-cleaning-a3f9
    image_digest:       str  # sha256:... — the container identity certified on-chain
    code_hash:          str  # SHA-256 of the actor's script
    requirements_hash:  str  # SHA-256 of requirements.txt
    input_hash:         str  # SHA-256 of the input file baked into the image


@dataclass
class RunResult:
    """Captured after the container exits."""
    status:            str        # "success" or "failed"
    exit_code:         int        # container exit code (−1 on timeout)
    output_minio_key:  str | None # stage-outputs/... — None if the run failed
    output_hash:       str | None # SHA-256 of the output file — None if failed
    logs_minio_key:    str        # run-logs/... — always written, even on failure


# ── Dockerfile written once per build ─────────────────────────────────────────
#
# Build phase (docker build) has network access — pip install runs here.
# Run phase (docker run) has --network none — no outbound traffic from actor code.
#
# {input_filename} is replaced with the actual filename before writing to disk.

_DOCKERFILE_TEMPLATE = """\
FROM python:3.11-slim

# Non-root user for sandbox security. UID 1000 matches the --user flag in run().
RUN useradd --create-home --uid 1000 --shell /bin/bash runner

# Install actor dependencies. Network is available at build time (pip needs it).
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy actor script and input data.
COPY script.py /app/script.py
COPY {input_filename} /data/input/{input_filename}

# Create the output directory and hand ownership to the runner user.
RUN mkdir -p /data/output && chown -R runner:runner /data /app

USER runner
WORKDIR /app

# Actor code reads input from INPUT_FILE and writes output to OUTPUT_DIR.
ENV INPUT_FILE=/data/input/{input_filename}
ENV OUTPUT_DIR=/data/output/

ENTRYPOINT ["python", "/app/script.py"]
"""


# ── ContainerRunner ───────────────────────────────────────────────────────────

class ContainerRunner:
    """Builds and runs one sandboxed Docker container per pipeline stage run."""

    # ── build ─────────────────────────────────────────────────────────────────

    def build(
        self,
        code_file:         str | Path,
        requirements_file: str | Path,
        input_file:        str | Path,
        stage_name:        str,
        pipeline_id:       str | int,
    ) -> BuildResult:
        """Build a Docker image containing the actor's code, requirements, and input file.

        The input file is baked into the image so the image digest represents
        both the code AND the exact data being processed — this is what gets
        certified on-chain as the container identity.

        Raises subprocess.CalledProcessError if the build fails (e.g. pip
        cannot install a package). The error message contains the build log.
        """
        code_file         = Path(code_file)
        requirements_file = Path(requirements_file)
        input_file        = Path(input_file)

        # Hash all three inputs before touching Docker.
        code_hash         = compute_hash(code_file)
        requirements_hash = compute_hash(requirements_file)
        input_hash        = compute_hash(input_file)

        # Unique tag per build so concurrent stage runs don't collide.
        image_tag = f"pipeline-{pipeline_id}-{stage_name}-{uuid.uuid4().hex[:8]}"

        build_dir = Path(tempfile.mkdtemp(prefix="pipeline-build-"))
        try:
            # Copy files into the build context with the names the Dockerfile expects.
            shutil.copy2(code_file,         build_dir / "script.py")
            shutil.copy2(requirements_file, build_dir / "requirements.txt")
            shutil.copy2(input_file,        build_dir / input_file.name)

            # Write the Dockerfile with the input filename substituted.
            (build_dir / "Dockerfile").write_text(
                _DOCKERFILE_TEMPLATE.format(input_filename=input_file.name)
            )

            # Build the image. Network is available here for pip install.
            subprocess.run(
                ["docker", "build", "-t", image_tag, "."],
                cwd=build_dir,
                check=True,           # raises on non-zero exit
                capture_output=True,
                text=True,
            )

            # Capture the image digest — this is the container identity we certify.
            # .Id gives the config digest (sha256:...) which is stable for a local image.
            inspect = subprocess.run(
                ["docker", "inspect", "--format", "{{.Id}}", image_tag],
                check=True,
                capture_output=True,
                text=True,
            )
            image_digest = inspect.stdout.strip()

        finally:
            # Always remove the build context — it contains actor code and input data.
            shutil.rmtree(build_dir, ignore_errors=True)

        return BuildResult(
            image_tag=image_tag,
            image_digest=image_digest,
            code_hash=code_hash,
            requirements_hash=requirements_hash,
            input_hash=input_hash,
        )

    # ── run ───────────────────────────────────────────────────────────────────

    def run(
        self,
        build:       BuildResult,
        stage_name:  str,
        pipeline_id: str | int,
        timeout:     int = 300,
    ) -> RunResult:
        """Run the built image sandboxed and store output + logs in MinIO.

        Uses docker run -d to start detached (returns container ID immediately),
        then docker wait to block until exit or timeout, then docker cp to
        extract output files without volume-mount permission issues.

        Always uploads logs to MinIO — even on failure — so errors are inspectable.
        Removes the container and image in a finally block to avoid disk buildup.
        """
        work_dir     = Path(tempfile.mkdtemp(prefix="pipeline-run-"))
        container_id: str | None = None

        try:
            # Start the container detached. Sandbox: no network, non-root, resource caps.
            create = subprocess.run(
                [
                    "docker", "run", "-d",
                    "--network", "none",      # no outbound traffic from actor code
                    "--user",   "1000:1000",  # run as non-root runner user
                    "--memory", "1g",
                    "--cpus",   "1.5",
                    build.image_tag,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            container_id = create.stdout.strip()

            # Block until the container exits or the timeout fires.
            try:
                wait = subprocess.run(
                    ["docker", "wait", container_id],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                exit_code = int(wait.stdout.strip())
            except subprocess.TimeoutExpired:
                subprocess.run(["docker", "kill", container_id], capture_output=True)
                exit_code = -1  # signals a timeout to the caller

            # Collect stdout + stderr for the logs artifact.
            logs_proc = subprocess.run(
                ["docker", "logs", container_id],
                capture_output=True,
                text=True,
            )
            logs = logs_proc.stdout + logs_proc.stderr

            # Upload logs to MinIO regardless of success or failure.
            logs_key  = f"pipeline_{pipeline_id}/{stage_name}/run.log"
            log_file  = work_dir / "run.log"
            log_file.write_text(logs)
            put(BUCKET_RUN_LOGS, logs_key, log_file)

            if exit_code != 0:
                return RunResult(
                    status="failed",
                    exit_code=exit_code,
                    output_minio_key=None,
                    output_hash=None,
                    logs_minio_key=logs_key,
                )

            # Extract files the actor wrote to /data/output/ inside the container.
            # docker cp avoids volume-mount permission issues — runs as daemon (root).
            output_dir = work_dir / "output"
            output_dir.mkdir()
            subprocess.run(
                ["docker", "cp", f"{container_id}:/data/output/.", str(output_dir)],
                check=True,
                capture_output=True,
            )

            output_files = [f for f in output_dir.iterdir() if f.is_file()]
            if not output_files:
                # Script exited 0 but wrote nothing — treat as failure.
                return RunResult(
                    status="failed",
                    exit_code=0,
                    output_minio_key=None,
                    output_hash=None,
                    logs_minio_key=logs_key,
                )

            # Take the first (and expected only) output file.
            output_file = output_files[0]
            output_key  = f"pipeline_{pipeline_id}/{stage_name}/output{output_file.suffix}"
            output_hash = put(BUCKET_STAGE_OUTPUTS, output_key, output_file)

            return RunResult(
                status="success",
                exit_code=0,
                output_minio_key=output_key,
                output_hash=output_hash,
                logs_minio_key=logs_key,
            )

        finally:
            # Clean up container and image regardless of outcome.
            if container_id:
                subprocess.run(["docker", "rm",           container_id],        capture_output=True)
            subprocess.run(    ["docker", "rmi", "--force", build.image_tag],   capture_output=True)
            shutil.rmtree(work_dir, ignore_errors=True)