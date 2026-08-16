#!/usr/bin/env python3
"""
Review / model stage service (multi-actor).

Run on behalf of the REVIEWER (Person C). This is the final stage. Unlike the
cleaning/training services there is NO compute step -- the model already exists.
The reviewer INDEPENDENTLY verifies the whole certificate chain on-chain, then
approves by certifying the model stage with their own key (their signature is
the approval).

  3. authenticate + prove role  -> RoleManager canCertify(model, personC)
  4. full-chain audit            -> dataset -> environment -> cleaning -> training
                                    each: local hash == on-chain, evidence re-hashed
  6. build + (implicitly) sign   -> model manifest, signed by Person C on submit
  7. certify (= approve)         -> anchor model cert via V2 (msg.sender = personC)

Any failed check stops the stage (the "reject" path).

Env used:
    PIPELINE_ID
    PERSON_C_PRIVATE_KEY
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


def verify_chain_link(backend, stage_label: str, receipt_path: str) -> None:
    """Independently verify one certificate in the chain.

    Checks three things and raises RuntimeError on any failure:
      1. the local manifest still hashes to what the receipt recorded,
      2. that hash is certified on the V2 registry for this pipeline,
      3. every evidence file re-hashes to its recorded value.
    """
    receipt = json.loads(Path(receipt_path).read_text())
    manifest_path = receipt["manifest_path"]
    recorded_hash = receipt["manifest_sha256"]

    # 1. local manifest integrity
    actual_hash = hash_file(manifest_path)
    if actual_hash != recorded_hash:
        raise RuntimeError(
            f"[{stage_label}] manifest hash changed: {manifest_path}")

    # 2. certified on-chain (V2, this pipeline)
    if not backend.is_certified(recorded_hash):
        raise RuntimeError(
            f"[{stage_label}] NOT certified on V2: {recorded_hash}")

    # 3. evidence files re-hash
    manifest = json.loads(Path(manifest_path).read_text())
    for ev in manifest.get("evidence_files", []):
        p = Path(ev["path"])
        if not p.exists():
            raise RuntimeError(f"[{stage_label}] evidence missing: {p}")
        if hash_file(str(p)) != ev["sha256"]:
            raise RuntimeError(f"[{stage_label}] evidence hash mismatch: {p}")

    print(f"   VERIFIED [{stage_label}] : {recorded_hash[:16]}...  "
          f"submitter-signed, on-chain, evidence intact")


def build_manifest(output_path: str, parent_receipts: list) -> str:
    """Build the model manifest via the existing manifest_service.py."""
    cmd = [
        sys.executable, "src/manifest_service.py",
        "--type", "model",
        "--output", output_path,
        "--overwrite",
        "--file", "model_artifact=artifacts/models/iris_nn_model.pkl",
        "--meta", "model_version=model_v3",
        "--meta", "reviewed=true",
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
    parser = argparse.ArgumentParser(description="Review/model stage service (Person C).")
    parser.add_argument("--pipeline-id", type=int,
                        default=int(os.getenv("PIPELINE_ID", "0")))
    # The full chain to audit (V2 / multi-actor receipts).
    parser.add_argument("--dataset-receipt",
                        default="certificates/receipts/ma_dataset_receipt.json")
    parser.add_argument("--environment-receipt",
                        default="certificates/receipts/ma_environment_v1_receipt.json")
    parser.add_argument("--cleaning-receipt",
                        default="certificates/receipts/ma_cleaning_receipt.json")
    parser.add_argument("--training-receipt",
                        default="certificates/receipts/ma_training_receipt.json")
    parser.add_argument("--manifest",
                        default="certificates/manifests/ma_model_manifest.json")
    parser.add_argument("--receipt",
                        default="certificates/receipts/ma_model_receipt.json")
    args = parser.parse_args()

    if not args.pipeline_id:
        print("PIPELINE_ID not set (use --pipeline-id or .env).", file=sys.stderr)
        sys.exit(1)

    actor_key = os.getenv("PERSON_C_PRIVATE_KEY")
    if not actor_key:
        print("PERSON_C_PRIVATE_KEY not set in .env.", file=sys.stderr)
        sys.exit(1)

    backend = MultiActorBackend(pipeline_id=args.pipeline_id)
    from web3 import Web3
    actor_address = Web3().eth.account.from_key(actor_key).address

    print("=== REVIEW / MODEL STAGE SERVICE (Person C / REVIEWER) ===")
    print(f"Pipeline: {args.pipeline_id}")
    print(f"Actor: {actor_address}\n")

    # Step 3: prove role
    print("--- Step 3: Authenticate + prove role ---")
    if not backend.can_certify("model", actor_address):
        print("REJECTED: actor is not authorized as REVIEWER for this pipeline.",
              file=sys.stderr)
        sys.exit(2)
    print("Role OK: actor may certify (approve) the model stage.\n")

    # Step 4: full-chain independent audit
    print("--- Step 4: Full-chain audit (reviewer verifies everything) ---")
    chain = [
        ("dataset",     args.dataset_receipt),
        ("environment", args.environment_receipt),
        ("cleaning",    args.cleaning_receipt),
        ("training",    args.training_receipt),
    ]
    try:
        for stage_label, receipt_path in chain:
            verify_chain_link(backend, stage_label, receipt_path)
    except RuntimeError as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        sys.exit(3)
    print("Full chain OK: dataset -> environment -> cleaning -> training all valid.\n")

    # Step 6: build model manifest (parent = training)
    print("--- Step 6: Build model manifest (approval) ---")
    build_manifest(args.manifest, [("training", args.training_receipt)])
    manifest_text = Path(args.manifest).read_text(encoding="utf-8")
    manifest_sha256 = hash_file(args.manifest)

    # Step 7: certify (reviewer signs = approves)
    print("\n--- Step 7: Sign + certify (approve) on-chain ---")
    receipt = backend.submit(actor_key, manifest_text, manifest_sha256)
    receipt["manifest_path"] = args.manifest

    out = Path(args.receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"\nReceipt saved: {out}")
    print("\nMODEL APPROVED + CERTIFIED BY PERSON C (REVIEWER)")


if __name__ == "__main__":
    main()