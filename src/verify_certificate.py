import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from circular_enterprise_apis import CEP_Account

from hashing import hash_file


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")

    return value.strip()


def decode_hex_text(hex_value: str) -> str:
    return bytes.fromhex(hex_value).decode("utf-8")


def verify_manifest_certificate(manifest_path: str, receipt_path: str) -> bool:
    manifest_file = Path(manifest_path)
    receipt_file = Path(receipt_path)

    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    if not receipt_file.exists():
        raise FileNotFoundError(f"Receipt file not found: {receipt_path}")

    load_dotenv()

    network = get_required_env("CIRCULAR_NETWORK")
    blockchain_address = get_required_env("CIRCULAR_BLOCKCHAIN_ADDRESS")
    wallet_address = get_required_env("CIRCULAR_WALLET_ADDRESS")

    local_manifest_text = manifest_file.read_text(encoding="utf-8")
    local_manifest_hash = hash_file(manifest_path)
    local_manifest = json.loads(local_manifest_text)

    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    tx_id = receipt["tx_id"]
    block_id = receipt["block_id"]

    print(f"Manifest: {manifest_path}")
    print(f"Local manifest SHA-256: {local_manifest_hash}")
    print(f"TxID: {tx_id}")
    print(f"Block ID: {block_id}")
    print("Retrieving certificate from Circular blockchain...")

    account = CEP_Account()

    try:
        account.set_network(network)
        account.set_blockchain(blockchain_address)

        if not account.open(wallet_address):
            raise RuntimeError(f"Failed to open account: {account.lastError}")

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
            on_chain_manifest_text = decode_hex_text(certified_data)
        except (ValueError, UnicodeDecodeError):
            on_chain_manifest_text = certified_data

        if on_chain_manifest_text != local_manifest_text:
            print("FAILED: Local manifest does not match the blockchain certificate.")
            return False

        artifact_path = local_manifest["artifact_path"]
        expected_artifact_hash = local_manifest["artifact_sha256"]
        current_artifact_hash = hash_file(artifact_path)

        if current_artifact_hash != expected_artifact_hash:
            print("FAILED: Artifact has changed after manifest creation.")
            print(f"Expected artifact hash: {expected_artifact_hash}")
            print(f"Current artifact hash:  {current_artifact_hash}")
            return False

        if receipt.get("manifest_sha256") != local_manifest_hash:
            print("FAILED: Receipt manifest hash does not match local manifest hash.")
            return False

        print("VERIFIED: Blockchain certificate matches local manifest.")
        print("VERIFIED: Raw artifact hash matches certified manifest.")
        print(f"Artifact: {artifact_path}")
        print(f"Artifact SHA-256: {current_artifact_hash}")
        return True

    finally:
        account.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify a Circular blockchain certificate against a local manifest and artifact."
    )
    parser.add_argument("--manifest", required=True, help="Path to local manifest JSON")
    parser.add_argument("--receipt", required=True, help="Path to blockchain receipt JSON")

    args = parser.parse_args()

    try:
        verified = verify_manifest_certificate(args.manifest, args.receipt)
        sys.exit(0 if verified else 1)
    except Exception as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
