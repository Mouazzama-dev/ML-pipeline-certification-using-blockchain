import json
from datetime import datetime, timezone
from pathlib import Path

from hashing import hash_file


PROJECT_ID = "iris_certified_ai_mvp"
STAGE_NAME = "stage_01_raw_dataset_baseline"

EVIDENCE_FILES = [
    "data/raw/IRIS.csv",
    "certificates/manifests/dataset_manifest.json",
    "certificates/receipts/dataset_receipt.json",
    "requirements.txt",
    "requirements.lock.txt",
    "README.md",
    ".gitignore",
    "certificates/manifests/stage_01_runtime_info.json",
    "src/hashing.py",
    "src/manifest_service.py",
    "src/certificate_service.py",
    "src/verify_certificate.py",
    "src/capture_runtime.py",
    "src/stage_manifest_service.py",
]


def build_evidence_list() -> list[dict]:
    evidence = []

    for file_path in EVIDENCE_FILES:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Required Stage 01 evidence file not found: {file_path}")

        evidence.append({
            "path": file_path,
            "sha256": hash_file(file_path)
        })

    return evidence


def create_stage_01_manifest() -> Path:
    dataset_receipt_path = Path("certificates/receipts/dataset_receipt.json")

    with dataset_receipt_path.open("r", encoding="utf-8") as file:
        dataset_receipt = json.load(file)

    stage_manifest = {
        "schema_version": "1.0",
        "project_id": PROJECT_ID,
        "stage": STAGE_NAME,
        "certificate_purpose": (
            "Certify the raw dataset baseline together with its environment, "
            "documentation, source code and existing dataset certificate reference."
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_certificates": [
            {
                "certificate_type": "dataset_artifact_certificate",
                "network": dataset_receipt["network"],
                "tx_id": dataset_receipt["tx_id"],
                "block_id": dataset_receipt["block_id"],
                "manifest_path": dataset_receipt["manifest_path"],
                "manifest_sha256": dataset_receipt["manifest_sha256"]
            }
        ],
        "evidence_files": build_evidence_list(),
        "security_note": (
            "No private keys or .env secret values are included in this manifest."
        )
    }

    output_path = Path("certificates/manifests/stage_01_raw_dataset_manifest.json")

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(stage_manifest, file, indent=2, sort_keys=True)
        file.write("\n")

    return output_path


if __name__ == "__main__":
    output = create_stage_01_manifest()

    print(f"Stage 01 manifest created: {output}")
    print(f"Stage 01 manifest SHA-256: {hash_file(str(output))}")

    with output.open("r", encoding="utf-8") as file:
        print(file.read())
