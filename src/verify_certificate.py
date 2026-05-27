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
    """
    Decode Circular hexadecimal payload content into UTF-8 text.
    """
    return bytes.fromhex(hex_value).decode("utf-8")


def get_on_chain_manifest_text(
    account: CEP_Account,
    block_id: str,
    tx_id: str
) -> str:
    """
    Retrieve a certificate transaction and return the manifest text stored on-chain.
    """
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
        raise RuntimeError("Transaction is not a Circular certificate transaction.")

    certified_data = payload["Data"]

    try:
        return decode_hex_text(certified_data)
    except (ValueError, UnicodeDecodeError):
        return certified_data


def get_evidence_files(manifest: dict) -> list[dict]:
    """
    Support both:
    - Existing dataset manifest schema v1.0
    - New reusable manifest schema v2.0
    """
    if "evidence_files" in manifest:
        return manifest["evidence_files"]

    if "artifact_path" in manifest and "artifact_sha256" in manifest:
        return [
            {
                "role": manifest.get("certificate_type", "artifact"),
                "path": manifest["artifact_path"],
                "sha256": manifest["artifact_sha256"]
            }
        ]

    raise ValueError(
        "Manifest contains neither evidence_files nor artifact_path/artifact_sha256."
    )


def verify_evidence_files(manifest: dict, evidence_root: Path) -> bool:
    """
    Recalculate each evidence file hash and compare it to its certified hash.
    """
    evidence_files = get_evidence_files(manifest)
    all_valid = True

    print("\n--- Verifying Certified Evidence Files ---")

    for evidence in evidence_files:
        role = evidence.get("role", "artifact")
        relative_path = Path(evidence["path"])
        evidence_path = evidence_root / relative_path
        expected_hash = evidence["sha256"]

        if not evidence_path.exists():
            print(f"FAILED: Missing {role} file: {evidence_path}")
            all_valid = False
            continue

        current_hash = hash_file(str(evidence_path))

        if current_hash == expected_hash:
            print(f"VERIFIED: {role} -> {relative_path}")
        else:
            print(f"FAILED: {role} -> {relative_path}")
            print(f"  Expected SHA-256: {expected_hash}")
            print(f"  Current SHA-256:  {current_hash}")
            all_valid = False

    return all_valid


def print_parent_references(manifest: dict) -> None:
    """
    Display parent links recorded in a manifest.
    Parent certificates are verified separately using this same script.
    """
    parents = manifest.get("parent_certificates", [])

    if not parents:
        return

    print("\n--- Recorded Parent Certificate References ---")

    for parent in parents:
        role = parent.get("role", "parent")
        tx_id = parent.get("tx_id", "not available")
        block_id = parent.get("block_id", "not available")

        print(f"{role}:")
        print(f"  TxID: {tx_id}")
        print(f"  Block ID: {block_id}")


def verify_certificate(
    manifest_path: str,
    receipt_path: str,
    evidence_root: str = "."
) -> bool:
    """
    Verify one certified manifest against Circular blockchain and local evidence files.
    """
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
    local_manifest = json.loads(local_manifest_text)
    local_manifest_hash = hash_file(str(manifest_file))

    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))

    tx_id = receipt["tx_id"]
    block_id = receipt["block_id"]

    certificate_type = local_manifest.get("certificate_type", "unknown")

    print("--- Verifying Certificate on Circular Blockchain ---")
    print(f"Certificate type: {certificate_type}")
    print(f"Manifest: {manifest_path}")
    print(f"Manifest SHA-256: {local_manifest_hash}")
    print(f"TxID: {tx_id}")
    print(f"Block ID: {block_id}")

    if receipt.get("manifest_sha256") != local_manifest_hash:
        print("FAILED: Receipt manifest hash does not match the current manifest.")
        return False

    account = CEP_Account()

    try:
        account.set_network(network)
        account.set_blockchain(blockchain_address)

        if not account.open(wallet_address):
            raise RuntimeError(f"Failed to open Circular account: {account.lastError}")

        on_chain_manifest_text = get_on_chain_manifest_text(
            account=account,
            block_id=block_id,
            tx_id=tx_id
        )

        if on_chain_manifest_text != local_manifest_text:
            print("FAILED: Local manifest does not match blockchain certificate.")
            return False

        print("VERIFIED: Local manifest matches blockchain certificate.")

    finally:
        account.close()

    print_parent_references(local_manifest)

    evidence_valid = verify_evidence_files(
        manifest=local_manifest,
        evidence_root=Path(evidence_root)
    )

    if not evidence_valid:
        print("\nFINAL RESULT: CERTIFICATE VERIFICATION FAILED")
        return False

    print(f"\nFINAL RESULT: {certificate_type.upper()} CERTIFICATE VERIFIED")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify any blockchain-certified AI pipeline manifest and its evidence files."
    )

    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to the certified manifest JSON file"
    )

    parser.add_argument(
        "--receipt",
        required=True,
        help="Path to the corresponding blockchain receipt JSON file"
    )

    parser.add_argument(
        "--evidence-root",
        default=".",
        help="Root folder containing the evidence files. Default: current project folder"
    )

    args = parser.parse_args()

    try:
        verified = verify_certificate(
            manifest_path=args.manifest,
            receipt_path=args.receipt,
            evidence_root=args.evidence_root
        )

        sys.exit(0 if verified else 1)

    except Exception as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
