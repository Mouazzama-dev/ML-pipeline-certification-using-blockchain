import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from hashing import hash_file


def capture_runtime_info(stage_name: str, output_path: str) -> Path:
    """
    Capture non-secret runtime and environment information for a pipeline stage.
    """
    requirements_lock = "requirements.lock.txt"

    if not Path(requirements_lock).exists():
        raise FileNotFoundError(f"Required file not found: {requirements_lock}")

    runtime_info = {
        "schema_version": "1.0",
        "project_id": "iris_certified_ai_mvp",
        "stage": stage_name,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable
        },
        "system": {
            "operating_system": platform.system(),
            "platform": platform.platform(),
            "release": platform.release(),
            "machine": platform.machine()
        },
        "dependency_snapshot": {
            "path": requirements_lock,
            "sha256": hash_file(requirements_lock)
        }
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(runtime_info, file, indent=2, sort_keys=True)
        file.write("\n")

    return output


if __name__ == "__main__":
    output = capture_runtime_info(
        stage_name="stage_01_raw_dataset_baseline",
        output_path="certificates/manifests/stage_01_runtime_info.json"
    )

    print(f"Runtime information saved: {output}")
    print(f"Runtime information SHA-256: {hash_file(str(output))}")

    with output.open("r", encoding="utf-8") as file:
        print(file.read())
