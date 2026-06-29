import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from circular_enterprise_apis import CEP_Account

from hashing import hash_file
from network_utils import call_with_retry


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")

    return value.strip()


def submit_manifest_certificate(manifest_path: str, receipt_path: str) -> dict:
    """
    Submit a manifest JSON file as a Circular blockchain certificate.
    This same function will later certify dataset, cleaning, training and model manifests.
    """
    manifest_file = Path(manifest_path)

    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    load_dotenv()

    network = get_required_env("CIRCULAR_NETWORK")
    blockchain_address = get_required_env("CIRCULAR_BLOCKCHAIN_ADDRESS")
    wallet_address = get_required_env("CIRCULAR_WALLET_ADDRESS")
    private_key = get_required_env("CIRCULAR_PRIVATE_KEY")

    if network not in {"testnet", "devnet", "mainnet"}:
        raise ValueError("CIRCULAR_NETWORK must be testnet, devnet or mainnet")

    manifest_data = manifest_file.read_text(encoding="utf-8")
    manifest_sha256 = hash_file(manifest_path)

    print(f"Manifest: {manifest_path}")
    print(f"Manifest SHA-256: {manifest_sha256}")
    print(f"Network: {network}")
    print("Submitting certificate to Circular...")

    account = CEP_Account()

    try:
        account.set_network(network)
        account.set_blockchain(blockchain_address)

        if not call_with_retry(account.open, wallet_address):
            raise RuntimeError(f"Failed to open account: {account.lastError}")

        if not call_with_retry(account.update_account):
            raise RuntimeError(f"Failed to update account: {account.lastError}")

        submission = call_with_retry(account.submit_certificate, manifest_data, private_key)

        if submission.get("Result") != 200:
            raise RuntimeError(f"Certificate submission failed: {submission}")

        tx_id = submission["Response"]["TxID"]
        print(f"Transaction submitted. TxID: {tx_id}")

        outcome = call_with_retry(account.get_transaction_outcome, tx_id, 25)

        block_id = outcome.get("Response", {}).get("BlockID")

        if not block_id:
            raise RuntimeError(f"Transaction was not confirmed: {outcome}")

        transaction = call_with_retry(account.get_transaction, block_id, tx_id)

        if transaction.get("Result") != 200:
            raise RuntimeError(f"Could not retrieve confirmed transaction: {transaction}")

        status = transaction.get("Response", {}).get("Status", "Unknown")

        receipt = {
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha256,
            "network": network,
            "blockchain_address": blockchain_address,
            "wallet_address": wallet_address,
            "tx_id": tx_id,
            "block_id": block_id,
            "status": status,
            "submission_response": submission,
            "outcome_response": outcome,
            "transaction_response": transaction,
        }

        output = Path(receipt_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("w", encoding="utf-8") as file:
            json.dump(receipt, file, indent=2)
            file.write("\n")

        print(f"Transaction status: {status}")
        print(f"Receipt saved: {output}")

        return receipt

    finally:
        account.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit an AI pipeline manifest as a Circular blockchain certificate."
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
