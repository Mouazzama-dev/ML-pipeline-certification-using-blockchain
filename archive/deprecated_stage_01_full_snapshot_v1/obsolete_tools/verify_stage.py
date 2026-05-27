import argparse
import json
import os
import sys
from pathlib import Path

from circular_enterprise_apis import CEP_Account
from dotenv import load_dotenv

from hashing import hash_file


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")

    return value.strip()


def decode_hex_text(hex_value: str) -> str:
    return bytes.fromhex(hex_value).decode("utf-8")


def get_on_chain_certificate_text(
    account: CEP_Account,
    block_id: str,
    tx_id: str
) -> str:
    transaction = account.get_transaction(block_id, tx_id)

    if transaction.get("Result") != 200:
        raise RuntimeError(f"Could not retrieve transaction: {transaction}")

    response = transaction["Response"]

    if response.get("Status") != "Executed":
        raise RuntimeError(
            f"Certificate transaction is not executed. Status: {response.get('Status')}"
        )

    payload_text = decode_hex_text(response["Payload"])
    payload = json.loads(payload_text)

    if payload.get("Action") != "CP_CERTIFICATE":
        raise RuntimeError("Transaction is not a certificate transaction.")

    certified_data = payload["Data"]

    try:
        return decode_hex_text(certified_data)
    except (ValueError, UnicodeDecodeError):
        return certified_data


def verify_manifest_on_chain(
    account: CEP_Account,
    manifest_path: Path,
    receipt_path: Path,
    label: str
) -> dict:
    if not manifest_path.exists():
        raise FileNotFoundError(f"{label} manifest not found: {manifest_path}")

    if not receipt_path.exists():
        raise FileNotFoundError(f"{label} receipt not found: {receipt_path}")

    local_manifest_text = manifest_path.read_text(encoding="utf-8")
    local_manifest_hash = hash_file(str(manifest_path))
    local_manifest = json.loads(local_manifest_text)

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    tx_id = receipt["tx_id"]
    block_id = receipt["block_id"]

    print(f"\n--- Verifying {label} on Blockchain ---")
    print(f"Manifest: {manifest_path}")
    print(f"Manifest SHA-256: {local_manifest_hash}")
    print(f"TxID: {tx_id}")
    print(f"Block ID: {block_id}")

    if receipt.get("manifest_sha256") != local_manifest_hash:
        raise RuntimeError(
            f"{label} receipt manifest hash does not match the local manifest."
        )

    on_chain_manifest_text = get_on_chain_certificate_text(
        account=account,
        block_id=block_id,
        tx_id=tx_id
    )

    if on_chain_manifest_text != local_manifest_text:
        raise RuntimeError(
            f"{label} local manifest does not match its blockchain certificate."
        )

    print(f"VERIFIED: {label} manifest matches blockchain certificate.")

    return local_manifest


def verify_artifact_manifest(
    account: CEP_Account,
    manifest_path: Path,
    receipt_path: Path,
    artifact_root: Path,
    label: str
) -> bool:
    manifest = verify_manifest_on_chain(
        account=account,
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        label=label
    )

    artifact_relative_path = Path(manifest["artifact_path"])
    artifact_path = artifact_root / artifact_relative_path

    if not artifact_path.exists():
        print(f"FAILED: Missing certified artifact: {artifact_path}")
        return False

    expected_hash = manifest["artifact_sha256"]
    current_hash = hash_file(str(artifact_path))

    if current_hash != expected_hash:
        print(f"FAILED: Certified artifact hash mismatch: {artifact_path}")
        print(f"Expected: {expected_hash}")
        print(f"Current:  {current_hash}")
        return False

    print(f"VERIFIED: Certified artifact matches manifest: {artifact_path}")
    return True


def verify_stage_evidence(stage_manifest: dict, evidence_root: Path) -> bool:
    print("\n--- Verifying Stage Evidence Files ---")

    all_valid = True

    for evidence in stage_manifest["evidence_files"]:
        relative_path = Path(evidence["path"])
        evidence_path = evidence_root / relative_path
        expected_hash = evidence["sha256"]

        if not evidence_path.exists():
            print(f"FAILED: Missing evidence file: {evidence_path}")
            all_valid = False
            continue

        current_hash = hash_file(str(evidence_path))

        if current_hash == expected_hash:
            print(f"VERIFIED: {relative_path}")
        else:
            print(f"FAILED: {relative_path}")
            print(f"Expected: {expected_hash}")
            print(f"Current:  {current_hash}")
            all_valid = False

    return all_valid


def verify_stage(
    stage_manifest_path: str,
    stage_receipt_path: str,
    evidence_root: str,
    parent_manifest_path: str | None = None,
    parent_receipt_path: str | None = None,
    parent_artifact_root: str | None = None
) -> bool:
    load_dotenv()

    network = get_required_env("CIRCULAR_NETWORK")
    blockchain_address = get_required_env("CIRCULAR_BLOCKCHAIN_ADDRESS")
    wallet_address = get_required_env("CIRCULAR_WALLET_ADDRESS")

    account = CEP_Account()

    try:
        account.set_network(network)
        account.set_blockchain(blockchain_address)

        if not account.open(wallet_address):
            raise RuntimeError(f"Failed to open Circular account: {account.lastError}")

        if parent_manifest_path and parent_receipt_path:
            parent_root = Path(parent_artifact_root or evidence_root)

            parent_valid = verify_artifact_manifest(
                account=account,
                manifest_path=Path(parent_manifest_path),
                receipt_path=Path(parent_receipt_path),
                artifact_root=parent_root,
                label="Parent Artifact Certificate"
            )

            if not parent_valid:
                print("\nFINAL RESULT: PARENT CERTIFICATE VERIFICATION FAILED")
                return False

        stage_manifest = verify_manifest_on_chain(
            account=account,
            manifest_path=Path(stage_manifest_path),
            receipt_path=Path(stage_receipt_path),
            label="Stage Certificate"
        )

        evidence_valid = verify_stage_evidence(
            stage_manifest=stage_manifest,
            evidence_root=Path(evidence_root)
        )

        if not evidence_valid:
            print("\nFINAL RESULT: STAGE VERIFICATION FAILED")
            return False

        print(f"\nFINAL RESULT: {stage_manifest['stage']} VERIFIED")
        return True

    finally:
        account.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify an archived or working blockchain-certified pipeline stage."
    )

    parser.add_argument("--stage-manifest", required=True)
    parser.add_argument("--stage-receipt", required=True)
    parser.add_argument("--evidence-root", required=True)

    parser.add_argument("--parent-manifest")
    parser.add_argument("--parent-receipt")
    parser.add_argument("--parent-artifact-root")

    args = parser.parse_args()

    if bool(args.parent_manifest) != bool(args.parent_receipt):
        print(
            "Both --parent-manifest and --parent-receipt must be provided together.",
            file=sys.stderr
        )
        sys.exit(1)

    try:
        verified = verify_stage(
            stage_manifest_path=args.stage_manifest,
            stage_receipt_path=args.stage_receipt,
            evidence_root=args.evidence_root,
            parent_manifest_path=args.parent_manifest,
            parent_receipt_path=args.parent_receipt,
            parent_artifact_root=args.parent_artifact_root
        )

        sys.exit(0 if verified else 1)

    except Exception as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
