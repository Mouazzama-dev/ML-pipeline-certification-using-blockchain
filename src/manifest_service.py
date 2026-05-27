import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from hashing import hash_file


PROJECT_ID = "iris_certified_ai_mvp"


def parse_key_value(value: str, argument_name: str) -> tuple[str, str]:
    """
    Parse command-line values in the form role=path or key=value.
    """
    if "=" not in value:
        raise ValueError(
            f"Invalid {argument_name} value '{value}'. Expected format: key=value"
        )

    key, item_value = value.split("=", 1)
    key = key.strip()
    item_value = item_value.strip()

    if not key or not item_value:
        raise ValueError(
            f"Invalid {argument_name} value '{value}'. Key and value are required."
        )

    return key, item_value


def ensure_not_secret_file(file_path: str) -> None:
    """
    Prevent secret configuration files from being included in blockchain manifests.
    """
    parts = Path(file_path).parts

    for part in parts:
        if part == ".env" or part.startswith(".env."):
            raise ValueError(
                f"Secret/config environment file must not be certified: {file_path}"
            )


def build_evidence_files(file_arguments: list[str]) -> list[dict]:
    """
    Convert repeated --file role=path arguments into hashed evidence entries.
    """
    evidence_files = []

    for argument in file_arguments:
        role, file_path = parse_key_value(argument, "--file")
        ensure_not_secret_file(file_path)

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Evidence file not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Evidence path is not a file: {file_path}")

        evidence_files.append({
            "role": role,
            "path": file_path,
            "sha256": hash_file(file_path)
        })

    return evidence_files


def build_parent_certificates(parent_arguments: list[str]) -> list[dict]:
    """
    Convert repeated --parent role=receipt_path arguments into certificate references.
    Only blockchain identifiers and certified manifest hash are included in the new manifest.
    """
    parent_certificates = []

    for argument in parent_arguments:
        role, receipt_path = parse_key_value(argument, "--parent")
        path = Path(receipt_path)

        if not path.exists():
            raise FileNotFoundError(f"Parent receipt not found: {receipt_path}")

        with path.open("r", encoding="utf-8") as file:
            receipt = json.load(file)

        required_fields = [
            "network",
            "tx_id",
            "block_id",
            "manifest_sha256"
        ]

        missing_fields = [
            field for field in required_fields if not receipt.get(field)
        ]

        if missing_fields:
            raise ValueError(
                f"Parent receipt '{receipt_path}' is missing fields: "
                f"{', '.join(missing_fields)}"
            )

        parent_certificates.append({
            "role": role,
            "network": receipt["network"],
            "tx_id": receipt["tx_id"],
            "block_id": receipt["block_id"],
            "manifest_sha256": receipt["manifest_sha256"]
        })

    return parent_certificates


def build_metadata(metadata_arguments: list[str]) -> dict:
    """
    Convert repeated --meta key=value arguments into manifest metadata.
    """
    metadata = {}

    for argument in metadata_arguments:
        key, value = parse_key_value(argument, "--meta")
        metadata[key] = value

    return metadata


def create_manifest(
    certificate_type: str,
    output_path: str,
    file_arguments: list[str],
    parent_arguments: list[str] | None = None,
    metadata_arguments: list[str] | None = None,
    overwrite: bool = False
) -> Path:
    """
    Create a generic certificate manifest for any AI pipeline stage.
    """
    output = Path(output_path)

    if output.exists() and not overwrite:
        raise FileExistsError(
            f"Manifest already exists: {output_path}. "
            "Do not overwrite a certified manifest. "
            "Use a new output name, or use --overwrite only before certification."
        )

    manifest = {
        "schema_version": "2.0",
        "project_id": PROJECT_ID,
        "certificate_type": certificate_type,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_certificates": build_parent_certificates(parent_arguments or []),
        "evidence_files": build_evidence_files(file_arguments),
        "metadata": build_metadata(metadata_arguments or [])
    }

    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2, sort_keys=True)
        file.write("\n")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a generic blockchain certificate manifest for an AI pipeline artifact or stage."
    )

    parser.add_argument(
        "--type",
        required=True,
        dest="certificate_type",
        help="Certificate type, for example: environment, cleaning, training or model"
    )

    parser.add_argument(
        "--output",
        required=True,
        dest="output_path",
        help="Output manifest JSON path"
    )

    parser.add_argument(
        "--file",
        action="append",
        required=True,
        dest="file_arguments",
        help="Evidence file in role=path format. Repeat for multiple files."
    )

    parser.add_argument(
        "--parent",
        action="append",
        default=[],
        dest="parent_arguments",
        help="Parent certificate in role=receipt_path format. Repeat when needed."
    )

    parser.add_argument(
        "--meta",
        action="append",
        default=[],
        dest="metadata_arguments",
        help="Metadata in key=value format. Repeat when needed."
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing manifest only before blockchain certification."
    )

    args = parser.parse_args()

    output = create_manifest(
        certificate_type=args.certificate_type,
        output_path=args.output_path,
        file_arguments=args.file_arguments,
        parent_arguments=args.parent_arguments,
        metadata_arguments=args.metadata_arguments,
        overwrite=args.overwrite
    )

    print(f"Manifest created: {output}")
    print(f"Manifest SHA-256: {hash_file(str(output))}")

    with output.open("r", encoding="utf-8") as file:
        print(file.read())


if __name__ == "__main__":
    main()
