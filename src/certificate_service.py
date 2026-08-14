"""
Submit an ML pipeline manifest as a blockchain certificate.

This module is now blockchain-agnostic: it hashes the manifest, asks the
factory for whichever backend is configured (Circular, Polygon, ...), and lets
that backend anchor the manifest and produce the receipt. It never references a
specific chain -- switching chains is done via BLOCKCHAIN in .env.
"""

import argparse
import json
import sys
from pathlib import Path

from hashing import hash_file
from blockchain.factory import get_backend


def submit_manifest_certificate(manifest_path: str, receipt_path: str) -> dict:
    """
    Anchor a manifest JSON file on whichever blockchain backend is configured.
    Works for dataset, cleaning, training and model manifests alike.
    """
    manifest_file = Path(manifest_path)
    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    manifest_text = manifest_file.read_text(encoding="utf-8")
    manifest_sha256 = hash_file(manifest_path)

    backend = get_backend()
    print(f"Backend: {backend.name}")
    print(f"Manifest: {manifest_path}")

    # The backend does the chain-specific work and returns a receipt dict.
    receipt = backend.submit(manifest_text, manifest_sha256)

    # Record where the manifest lived locally, then save the receipt.
    receipt["manifest_path"] = manifest_path

    output = Path(receipt_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(receipt, file, indent=2)
        file.write("\n")

    print(f"Receipt saved: {output}")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit an AI pipeline manifest as a blockchain certificate."
    )
    parser.add_argument("--manifest", required=True, help="Path to manifest JSON file")
    parser.add_argument("--receipt", required=True, help="Path to save blockchain receipt JSON")
    args = parser.parse_args()

    try:
        submit_manifest_certificate(args.manifest, args.receipt)
    except Exception as error:
        print(f"Certification failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()