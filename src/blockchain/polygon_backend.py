"""
Polygon backend.

Anchors each stage manifest on an EVM chain (Polygon Amoy by default) through
the CertificationRegistry smart contract. Unlike the Circular backend, only the
manifest HASH goes on-chain -- the contract stores hash + stage + parent hashes
and enforces the parent-child chain itself.

Because the manifest text is not stored on-chain, verification here is
hash-based: fetch_certificate() confirms the manifest hash is certified on-chain
and returns the manifest text only if the local hash matches what the caller
holds. This is the same security guarantee (the hash is the proof), just done
against the contract instead of decoding an on-chain payload.

Required environment (.env):
    BLOCKCHAIN=polygon
    POLYGON_RPC_URL=https://polygon-amoy-bor-rpc.publicnode.com
    POLYGON_PRIVATE_KEY=0x....
    POLYGON_CONTRACT_ADDRESS=0x....
    POLYGON_NETWORK=amoy            # label only, stored in the receipt
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .base import BlockchainBackend



def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value.strip()


def _hash_to_bytes32(sha256_hex: str) -> bytes:
    """Convert a 64-char SHA-256 hex string into 32 bytes for a bytes32 arg."""
    clean = sha256_hex[2:] if sha256_hex.startswith("0x") else sha256_hex
    if len(clean) != 64:
        raise ValueError(f"Expected a 64-char SHA-256 hex, got length {len(clean)}")
    return bytes.fromhex(clean)


def _load_abi() -> list:
    """
    Load the contract ABI. Looks for certification_registry_abi.json next to this
    file (copy it there from the Foundry build output).
    """
    abi_path = Path(__file__).parent / "certification_registry_abi.json"
    if not abi_path.exists():
        raise FileNotFoundError(
            f"Contract ABI not found at {abi_path}. Copy the ABI from "
            "blockchain-contracts/out/CertificationRegistry.sol/CertificationRegistry.json "
            "(the 'abi' field) into that file."
        )
    return json.loads(abi_path.read_text(encoding="utf-8"))


class PolygonBackend(BlockchainBackend):
    name = "polygon"

    def _connect(self):
        """Set up web3, the account, and the contract object."""
        from web3 import Web3
        from web3.middleware import ExtraDataToPOAMiddleware

        load_dotenv()
        rpc_url = _get_required_env("POLYGON_RPC_URL")
        private_key = _get_required_env("POLYGON_PRIVATE_KEY")
        contract_address = _get_required_env("POLYGON_CONTRACT_ADDRESS")

        w3 = Web3(Web3.HTTPProvider(rpc_url))
        # Polygon Amoy is a Proof-of-Authority chain: its block extraData
        # exceeds the 32 bytes web3 expects, so inject the PoA middleware.
        # Without this, any call that reads a block header fails.
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if not w3.is_connected():
            raise RuntimeError(f"Could not connect to RPC: {rpc_url}")

        account = w3.eth.account.from_key(private_key)
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_load_abi(),
        )
        return w3, account, contract

    def _parent_hashes(self, manifest_text: str) -> list:
        """Extract parent manifest hashes (as bytes32) from the manifest JSON."""
        manifest = json.loads(manifest_text)
        parents = manifest.get("parent_certificates", [])
        return [_hash_to_bytes32(p["manifest_sha256"]) for p in parents]

    def _stage_name(self, manifest_text: str) -> str:
        manifest = json.loads(manifest_text)
        return manifest.get("certificate_type", "unknown")

    def submit(self, manifest_text: str, manifest_sha256: str) -> dict:
        from web3 import Web3

        w3, account, contract = self._connect()
        network = os.getenv("POLYGON_NETWORK", "amoy").strip()

        manifest_hash = _hash_to_bytes32(manifest_sha256)
        stage = self._stage_name(manifest_text)
        parents = self._parent_hashes(manifest_text)

        print(f"Manifest SHA-256: {manifest_sha256}")
        print(f"Stage: {stage}  |  parents: {len(parents)}")
        print(f"Network: {network}")
        print("Submitting certificate to Polygon contract...")

        # Build, sign and send the storeCertificate transaction.
        tx = contract.functions.storeCertificate(
            manifest_hash, stage, parents
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": w3.eth.chain_id,
        })

        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"Transaction sent: {tx_hash.hex()}")

        receipt_chain = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        status = "Executed" if receipt_chain.status == 1 else "Failed"
        if status != "Executed":
            raise RuntimeError(f"Transaction failed on-chain: {tx_hash.hex()}")

        # Effective gas price actually paid (wei). Combined with gas_used this
        # gives the exact on-chain cost, so estimate_cost_polygon.py works from
        # real data instead of an assumed gas price.
        gas_price_wei = getattr(receipt_chain, "effectiveGasPrice", None)
        if gas_price_wei is None:
            gas_price_wei = w3.eth.gas_price
        cost_wei = receipt_chain.gasUsed * int(gas_price_wei)

        receipt = {
            "backend": self.name,
            "manifest_sha256": manifest_sha256,
            "network": network,
            "contract_address": contract.address,
            "wallet_address": account.address,
            "tx_id": tx_hash.hex(),
            "block_id": str(receipt_chain.blockNumber),
            "status": status,
            "gas_used": receipt_chain.gasUsed,
            "gas_price_wei": int(gas_price_wei),
            "cost_wei": int(cost_wei),
            "cost_pol": float(w3.from_wei(cost_wei, "ether")),
        }
        self.validate_receipt(receipt)
        print(f"Transaction status: {status}  |  gas used: {receipt_chain.gasUsed}"
              f"  |  cost: {receipt['cost_pol']:.8f} POL")
        return receipt

    def fetch_certificate(self, receipt: dict) -> str:
        """
        Confirm the manifest hash in the receipt is certified on-chain.

        Returns a small JSON string describing the on-chain record. The caller
        (verify_certificate.py) already compares the local manifest hash to
        receipt['manifest_sha256'] before calling this, and re-hashes evidence
        files afterwards, so confirming on-chain existence completes the proof.
        """
        _, _, contract = self._connect()
        manifest_hash = _hash_to_bytes32(receipt["manifest_sha256"])

        if not contract.functions.isCertified(manifest_hash).call():
            raise RuntimeError("Manifest hash is NOT certified on-chain.")

        stage, parents, submitter, timestamp = contract.functions.getCertificate(
            manifest_hash
        ).call()

        on_chain = {
            "manifest_sha256": receipt["manifest_sha256"],
            "stage": stage,
            "parent_count": len(parents),
            "submitter": submitter,
            "timestamp": timestamp,
            "certified": True,
        }
        return json.dumps(on_chain, sort_keys=True)

    def verify_on_chain(self, receipt: dict, local_manifest_text: str) -> bool:
        """
        Polygon stores only the hash. The caller already checked that the local
        manifest hash equals receipt['manifest_sha256']; here we confirm that
        exact hash is certified on-chain in the contract.
        """
        _, _, contract = self._connect()
        manifest_hash = _hash_to_bytes32(receipt["manifest_sha256"])
        return contract.functions.isCertified(manifest_hash).call()