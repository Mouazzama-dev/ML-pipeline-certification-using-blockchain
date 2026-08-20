#!/usr/bin/env python3
"""
Training stage service (multi-actor).

Run on behalf of the MODEL_TRAINER (Person B). Mirrors cleaning_service.py but
for the training stage:

  3. authenticate + prove role  -> RoleManager canCertify(training, personB)
  4. verify parents on-chain     -> cleaning + environment certified in pipeline
  5. execute                     -> run train_model.py
  6. build + (implicitly) sign   -> manifest, signed by Person B's key on submit
  7. certify                     -> anchor via V2 registry (msg.sender = personB)

Any failed check stops the stage (the "unauthorized / mismatch -> reject" path).

Env used:
    PIPELINE_ID
    PERSON_B_PRIVATE_KEY
    POLYGON_RPC_URL, ROLE_MANAGER_ADDRESS, POLYGON_CONTRACT_ADDRESS_V2
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Make src/ importable no matter where this script is launched from
# (it lives in src/services/, so its parent's parent is src/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from hashing import hash_file
from blockchain.multiactor_backend import MultiActorBackend


def run_training() -> None:
    """Execute training (reuses existing train_model.py).

    train_model.py has its OWN (single-actor) parent verification. In the
    multi-actor flow the REAL parent check already happened on the V2 registry
    (Step 4 below), so here we point train_model.py at the polygon_ parent certs
    that exist on the single-actor contract. This satisfies train_model.py
    WITHOUT modifying it -- keeping the single-actor demo (run_polygon_demo.sh)
    working unchanged.
    """
    print("\n--- Running Neural Network Training ---")
    result = subprocess.run(
        [
            sys.executable, "src/train_model.py", "--overwrite",
            "--cleaning-manifest",
            "certificates/manifests/polygon_cleaning_manifest.json",
            "--cleaning-receipt",
            "certificates/receipts/polygon_cleaning_receipt.json",
            "--environment-manifest",
            "certificates/manifests/polygon_environment_v1_manifest.json",
            "--environment-receipt",
            "certificates/receipts/polygon_environment_v1_receipt.json",
        ],
        capture_output=True, text=True,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Training step failed.")


def build_manifest(output_path: str, parent_receipts: list) -> str:
    """Build the training manifest via the existing manifest_service.py."""
    cmd = [
        sys.executable, "src/manifest_service.py",
        "--type", "training",
        "--output", output_path,
        "--overwrite",
        "--file", "training_script=src/train_model.py",
        "--file", "training_log=artifacts/logs/training_log.json",
        "--meta", "training_version=training_v3",
    ]
    for role, receipt in parent_receipts:
        cmd += ["--parent", f"{role}={receipt}"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("Manifest creation failed.")
    return output_path


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Training stage service (Person B).")
    parser.add_argument("--pipeline-id", type=int,
                        default=int(os.getenv("PIPELINE_ID", "0")))
    # Parent receipts default to the V2 (multi-actor) receipts so the training
    # manifest records the V2 tx/block as its parent references.
    parser.add_argument("--cleaning-receipt",
                        default="certificates/receipts/ma_cleaning_receipt.json")
    parser.add_argument("--environment-receipt",
                        default="certificates/receipts/ma_environment_v1_receipt.json")
    parser.add_argument("--manifest",
                        default="certificates/manifests/ma_training_manifest.json")
    parser.add_argument("--receipt",
                        default="certificates/receipts/ma_training_receipt.json")
    args = parser.parse_args()

    if not args.pipeline_id:
        print("PIPELINE_ID not set (use --pipeline-id or .env).", file=sys.stderr)
        sys.exit(1)

    actor_key = os.getenv("PERSON_B_PRIVATE_KEY")
    if not actor_key:
        print("PERSON_B_PRIVATE_KEY not set in .env.", file=sys.stderr)
        sys.exit(1)

    backend = MultiActorBackend(pipeline_id=args.pipeline_id)
    from web3 import Web3
    actor_address = Web3().eth.account.from_key(actor_key).address

    print("=== TRAINING STAGE SERVICE (Person B / MODEL_TRAINER) ===")
    print(f"Pipeline: {args.pipeline_id}")
    print(f"Actor: {actor_address}\n")

    # Step 3: prove role
    print("--- Step 3: Authenticate + prove role ---")
    if not backend.can_certify("training", actor_address):
        print("REJECTED: actor is not authorized as MODEL_TRAINER for this pipeline.",
              file=sys.stderr)
        sys.exit(2)
    print("Role OK: actor may certify the training stage.\n")

    # Step 4: verify parents on-chain
    print("--- Step 4: Verify parent certificates on-chain ---")
    cleaning_hash = json.loads(Path(args.cleaning_receipt).read_text())["manifest_sha256"]
    env_hash = json.loads(Path(args.environment_receipt).read_text())["manifest_sha256"]
    if not backend.parents_exist([cleaning_hash, env_hash]):
        print("REJECTED: cleaning/environment parent certificate missing on-chain.",
              file=sys.stderr)
        sys.exit(3)
    print("Parents OK: cleaning + environment are certified in this pipeline.\n")

    # Step 5: execute
    run_training()

    # Step 6: build manifest (will be signed by Person B on submit)
    print("\n--- Step 6: Build manifest ---")
    build_manifest(args.manifest, [
        ("cleaning", args.cleaning_receipt),
        ("environment", args.environment_receipt),
    ])
    manifest_text = Path(args.manifest).read_text(encoding="utf-8")
    manifest_sha256 = hash_file(args.manifest)

    # Step 7: certify (actor signs + anchors)
    print("\n--- Step 7: Sign + certify on-chain ---")
    receipt = backend.submit(actor_key, manifest_text, manifest_sha256)
    receipt["manifest_path"] = args.manifest

    out = Path(args.receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"\nReceipt saved: {out}")
    print("\nTRAINING STAGE CERTIFIED BY PERSON B")


if __name__ == "__main__":
    main()