#!/usr/bin/env python3
"""
certify_root_on_v2.py
---------------------
Admin helper: certify the ROOT stages (dataset, environment) on the V2
registry for a given pipeline.

Root stages have no role gate (canCertify == true for anyone), so the pipeline
ADMIN anchors them here. This is what lets the downstream role-gated stages
(cleaning, training, ...) find their parents already certified on V2.

It REUSES the existing single-actor manifests (same file content => same
SHA-256 hash), so the hash certified here is exactly the parent hash the
cleaning service will look up on-chain.

Idempotent: if a root stage is already certified on V2, it is skipped, so
re-running is safe.

Place this file in src/ and run from the repo root:
    python src/certify_root_on_v2.py --pipeline-id 1

Reads from .env:
    POLYGON_RPC_URL
    POLYGON_PRIVATE_KEY            # ADMIN key (pipeline admin)
    ROLE_MANAGER_ADDRESS
    POLYGON_CONTRACT_ADDRESS_V2    # the V2 registry
    PIPELINE_ID                    # or pass --pipeline-id

Writes V2 receipts (for the audit trail) to:
    certificates/receipts/ma_dataset_receipt.json
    certificates/receipts/ma_environment_v1_receipt.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from hashing import hash_file
from blockchain.multiactor_backend import MultiActorBackend


# stage -> (existing manifest to reuse, V2 receipt to write)
ROOTS = [
    ("dataset",
     "certificates/manifests/polygon_dataset_manifest.json",
     "certificates/receipts/ma_dataset_receipt.json"),
    ("environment",
     "certificates/manifests/polygon_environment_v1_manifest.json",
     "certificates/receipts/ma_environment_v1_receipt.json"),
]


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Certify root stages (dataset, environment) on the V2 registry."
    )
    parser.add_argument("--pipeline-id", type=int,
                        default=int(os.getenv("PIPELINE_ID", "0")))
    args = parser.parse_args()

    if not args.pipeline_id:
        print("PIPELINE_ID not set (use --pipeline-id or .env).", file=sys.stderr)
        sys.exit(1)

    admin_key = os.getenv("POLYGON_PRIVATE_KEY")
    if not admin_key:
        print("POLYGON_PRIVATE_KEY (admin) not set in .env.", file=sys.stderr)
        sys.exit(1)

    backend = MultiActorBackend(pipeline_id=args.pipeline_id)

    from web3 import Web3
    admin_addr = Web3().eth.account.from_key(admin_key).address

    print(f"=== Certify ROOT stages on V2 (pipeline {args.pipeline_id}) ===")
    print(f"Admin: {admin_addr}\n")

    for stage, manifest_path, receipt_path in ROOTS:
        if not Path(manifest_path).exists():
            print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)

        manifest_hash = hash_file(manifest_path)
        print(f"--- {stage} ---")
        print(f"manifest : {manifest_path}")
        print(f"hash     : {manifest_hash}")

        if backend.is_certified(manifest_hash):
            print("Already certified on V2 — skipping.\n")
            continue

        manifest_text = Path(manifest_path).read_text(encoding="utf-8")
        receipt = backend.submit(admin_key, manifest_text, manifest_hash)
        receipt["manifest_path"] = manifest_path

        out = Path(receipt_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"Receipt saved: {receipt_path}\n")

    print("Root stages ready on V2. You can now run the cleaning service.")


if __name__ == "__main__":
    main()