import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from hashing import hash_file


PROJECT_ID = "iris_certified_ai_mvp"


def create_environment_snapshot(
    label: str,
    dependency_lock_path: str,
    output_path: str,
    overwrite: bool = False
) -> Path:
    """
    Create a reusable, non-secret environment snapshot for certification.
    """
    dependency_lock = Path(dependency_lock_path)
    output = Path(output_path)

    if not dependency_lock.exists():
        raise FileNotFoundError(
            f"Dependency lock file not found: {dependency_lock_path}"
        )

    if output.exists() and not overwrite:
        raise FileExistsError(
            f"Environment snapshot already exists: {output_path}. "
            "Do not overwrite a certified snapshot. "
            "Use a new version label/output path instead."
        )

    pip_version = subprocess.check_output(
        [sys.executable, "-m", "pip", "--version"],
        text=True
    ).strip().split()[1]

    snapshot = {
        "schema_version": "1.0",
        "project_id": PROJECT_ID,
        "environment_label": label,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "compiler": platform.python_compiler(),
            "virtual_environment_active": sys.prefix != sys.base_prefix
        },
        "pip": {
            "version": pip_version
        },
        "system": {
            "operating_system": platform.system(),
            "release": platform.release(),
            "platform": platform.platform(),
            "machine": platform.machine()
        },
        "dependency_lock": {
            "path": dependency_lock_path,
            "sha256": hash_file(dependency_lock_path)
        },
        "security_note": "No wallet address, private key or .env values are included."
    }

    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(snapshot, file, indent=2, sort_keys=True)
        file.write("\n")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a reusable environment snapshot for blockchain certification."
    )

    parser.add_argument(
        "--label",
        required=True,
        help="Environment version label, for example environment_v1"
    )

    parser.add_argument(
        "--dependency-lock",
        required=True,
        help="Path to the exact dependency lock file"
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Path for the generated environment snapshot JSON"
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite only before blockchain certification"
    )

    args = parser.parse_args()

    output = create_environment_snapshot(
        label=args.label,
        dependency_lock_path=args.dependency_lock,
        output_path=args.output,
        overwrite=args.overwrite
    )

    print(f"Environment snapshot created: {output}")
    print(f"Environment snapshot SHA-256: {hash_file(str(output))}")

    with output.open("r", encoding="utf-8") as file:
        print(file.read())


if __name__ == "__main__":
    main()
