"""
Circular backend.

This wraps the ORIGINAL Circular Testnet logic (previously inline in
certificate_service.py and verify_certificate.py) behind the shared
BlockchainBackend interface. No behaviour is changed: it opens a CEP_Account,
submits the manifest as a certificate, waits for confirmation, and can read the
manifest back from the on-chain payload for verification.

It is kept so that:
  1. the existing, already-certified receipts remain fully verifiable, and
  2. the thesis can present Circular as one backend of the agnostic system
     rather than as discarded code.
"""

import os

from dotenv import load_dotenv

from .base import BlockchainBackend

# Circular SDK is only needed when this backend is actually used, so import it
# lazily inside methods. That way the project still runs (on Polygon, say) even
# on a machine where circular_enterprise_apis is not installed.


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value.strip()


def _decode_hex_text(hex_value: str) -> str:
    """Decode a Circular hexadecimal payload into UTF-8 text."""
    return bytes.fromhex(hex_value).decode("utf-8")


class CircularBackend(BlockchainBackend):
    name = "circular"

    def submit(self, manifest_text: str, manifest_sha256: str) -> dict:
        from circular_enterprise_apis import CEP_Account
        from network_utils import call_with_retry

        load_dotenv()
        network = _get_required_env("CIRCULAR_NETWORK")
        blockchain_address = _get_required_env("CIRCULAR_BLOCKCHAIN_ADDRESS")
        wallet_address = _get_required_env("CIRCULAR_WALLET_ADDRESS")
        private_key = _get_required_env("CIRCULAR_PRIVATE_KEY")

        if network not in {"testnet", "devnet", "mainnet"}:
            raise ValueError("CIRCULAR_NETWORK must be testnet, devnet or mainnet")

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

            submission = call_with_retry(account.submit_certificate, manifest_text, private_key)
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
                "backend": self.name,
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
            self.validate_receipt(receipt)
            print(f"Transaction status: {status}")
            return receipt
        finally:
            account.close()

    def fetch_certificate(self, receipt: dict) -> str:
        from circular_enterprise_apis import CEP_Account
        from network_utils import call_with_retry

        load_dotenv()
        network = _get_required_env("CIRCULAR_NETWORK")
        blockchain_address = _get_required_env("CIRCULAR_BLOCKCHAIN_ADDRESS")
        wallet_address = _get_required_env("CIRCULAR_WALLET_ADDRESS")

        account = CEP_Account()
        try:
            account.set_network(network)
            account.set_blockchain(blockchain_address)
            call_with_retry(account.open, wallet_address)
            call_with_retry(account.update_account)

            transaction = call_with_retry(
                account.get_transaction, receipt["block_id"], receipt["tx_id"]
            )
            if transaction.get("Result") != 200:
                raise RuntimeError(f"Could not retrieve transaction: {transaction}")

            response = transaction["Response"]
            if response.get("Status") != "Executed":
                raise RuntimeError(
                    f"Certificate transaction is not executed. Status: {response.get('Status')}"
                )

            payload = __import__("json").loads(_decode_hex_text(response["Payload"]))
            if payload.get("Action") != "CP_CERTIFICATE":
                raise RuntimeError("Transaction is not a Circular certificate transaction.")

            certified_data = payload["Data"]
            try:
                return _decode_hex_text(certified_data)
            except (ValueError, UnicodeDecodeError):
                return certified_data
        finally:
            account.close()

    def verify_on_chain(self, receipt: dict, local_manifest_text: str) -> bool:
        """Circular stored the full manifest text; compare it exactly."""
        on_chain_text = self.fetch_certificate(receipt)
        return on_chain_text == local_manifest_text