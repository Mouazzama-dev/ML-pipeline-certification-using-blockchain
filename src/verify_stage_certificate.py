import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from circular_enterprise_apis import CEP_Account

from hashing import hash_file
from verify_certificate import verify_manifest_certificate


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")

    return value.strip()


def decode_hex_text(hex_value: str) -> str:
    return bytes.fromhex(hex_value).decode("utf-8")


def verify_stage_manifest(stage_manifest_path: str, stage_receipt_path: str) -> bool:
    manifest_file = Path(stage_manifest_path)
    receipt_file = Path(stage_receipt_path)

    if not manifest_file.exists():
        raise FileNotFoundError(f"Stage manifest not found: {stage_manifest_path}")

    if not receipt_file.exists():
        raise FileNotFoundError(f"Stage receipt not found: {stage_receipt_path}")

    load_dotenv()

    network = get_required_env("CIRCULAR_NETWORK")
    blockchain_address = get_required_env("CIRCULAR_BLOCKCHAIN_ADDRESS")
    wallet_address = get_required_env("CIRCULAR_WALLET_ADDRESS")

    local_manifest_text = manifest_file.read_text(encoding="utf-8")
    local_manifest = json.loads(local_manifest_text)
    local_manifest_hash = hash_file(stage_manifest_path)

    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    tx_id = receipt["tx_id"]
    block_id = receipt["block_id"]

    print("\n--- Verifying Stage Certificate on Blockchain ---")
    print(f"Stage manifest: {stage_manifest_path}")
    print(f"Stage manifest SHA-256: {local_manifest_hash}")
    print(f"TxID: {tx_id}")
    print(f"Block ID: {block_id}")

    if receipt.get("manifest_sha256") != local_manifest_hash:
        print("FAILED: Receipt manifest hash does not match current local manifest.")
        return False

    account = CEP_Account()

    try:
        account.set_network(network)
        account.set_blockchain(blockchain_address)

        if not account.open(wallet_address):
            raise RuntimeError(f"Failed to open account: {account.lastError}")

        transaction = account.get_transaction(block_id, tx_id)

        if transaction.get("Result") != 200:
            raise RuntimeError(f"Could not retrieve Stage 01 transaction: {transaction}")

        response = transaction["Response"]

        if response.get("Status") != "Executed":
            print(f"FAILED: Stage transaction status is {response.get('Status')}")
            return False

        payload_text = decode_hex_text(response["Payload"])
        payload = json.loads(payload_text)

        if payload.get("Action") != "CP_CERTIFICATE":
            print("FAILED: Transaction is not a certificate transaction.")
            return False

        on_chain_manifest_text = decode_hex_text(payload["Data"])

        if on_chain_manifest_text != local_manifest_text:
            print("FAILED: Local Stage 01 manifest does not match blockchain certificate.")
            return False

        print("VERIFIED: Local Stage 01 manifest matches blockchain certificate.")

    finally:
        account.close()

    print("\n--- Verifying Stage 01 Evidence Files ---")

    all_files_valid = True

    for evidence in local_manifest["evidence_files"]:
        file_path = evidence["path"]
        expected_hash = evidence["sha256"]
        path = Path(file_path)

        if not path.exists():
            print(f"FAILED: Missing evidence file: {file_path}")
            all_files_valid = False
            continue

        current_hash = hash_file(file_path)

        if current_hash == expected_hash:
            print(f"VERIFIED: {file_path}")
        else:
            print(f"FAILED: {file_path}")
            print(f"  Expected: {expected_hash}")
            print(f"  Current:  {current_hash}")
            all_files_valid = False

    if not all_files_valid:
        print("\nFINAL RESULT: STAGE 01 VERIFICATION FAILED")
        return False

    print("\nFINAL RESULT: STAGE 01 RAW DATASET BASELINE VERIFIED")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Stage 01 certificate, evidence files and parent dataset certificate."
    )
    parser.add_argument("--manifest", required=True, help="Path to Stage 01 manifest JSON")
    parser.add_argument("--receipt", required=True, help="Path to Stage 01 receipt JSON")

    args = parser.parse_args()

    try:
        print("--- Verifying Parent Dataset Artifact Certificate ---")

        parent_verified = verify_manifest_certificate(
            "certificates/manifests/dataset_manifest.json",
            "certificates/receipts/dataset_receipt.json"
        )

        if not parent_verified:
            print("FINAL RESULT: Parent dataset certificate verification failed.")
            sys.exit(1)

        stage_verified = verify_stage_manifest(args.manifest, args.receipt)
        sys.exit(0 if stage_verified else 1)

    except Exception as error:
        print(f"Stage verification failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
