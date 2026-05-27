import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from hashing import hash_file


PROJECT_ID = "iris_certified_ai_mvp"


def create_manifest(
    certificate_type: str,
    artifact_path: str,
    output_path: str,
    parent_certificates: list[str] | None = None,
    description: str = "",
) -> Path:
    """
    Create a manifest describing one certified pipeline artifact.
    The saved manifest will later be certified on blockchain.
    """
    artifact = Path(artifact_path)

    if not artifact.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    manifest = {
        "schema_version": "1.0",
        "project_id": PROJECT_ID,
        "certificate_type": certificate_type,
        "artifact_path": artifact_path,
        "artifact_sha256": hash_file(artifact_path),
        "parent_certificates": parent_certificates or [],
        "metadata": {
            "description": description
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat()
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2, sort_keys=True)
        file.write("\n")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an artifact certificate manifest.")
    parser.add_argument("--type", required=True, dest="certificate_type")
    parser.add_argument("--artifact", required=True, dest="artifact_path")
    parser.add_argument("--output", required=True, dest="output_path")
    parser.add_argument("--parent", action="append", default=[], dest="parent_certificates")
    parser.add_argument("--description", default="")

    args = parser.parse_args()

    output = create_manifest(
        certificate_type=args.certificate_type,
        artifact_path=args.artifact_path,
        output_path=args.output_path,
        parent_certificates=args.parent_certificates,
        description=args.description,
    )

    print(f"Manifest created: {output}")
    print(f"Manifest SHA-256: {hash_file(str(output))}")

    with output.open("r", encoding="utf-8") as file:
        print(json.dumps(json.load(file), indent=2))


if __name__ == "__main__":
    main()
