"""
Multi-actor Polygon backend (V2 contracts).

This is the multi-actor counterpart of polygon_backend.py. Instead of one wallet
certifying everything, each stage is submitted by a specific ACTOR wallet, into a
specific PIPELINE, against the per-pipeline role-aware CertificationRegistry (V2)
and its RoleManager.

Responsibilities (mirrors the workflow diagram):
  - can_certify()      -> ask RoleManager if this actor may certify this stage
  - parents_exist()    -> confirm parent certificates exist in this pipeline
  - submit()           -> actor signs & anchors the manifest hash
  - is_certified()     -> read-back check for verification

Each actor's private key is passed in explicitly, so the caller (a stage
service) controls which identity signs. Only the manifest HASH goes on-chain;
msg.sender records which actor did it.

Env used:
    POLYGON_RPC_URL
    ROLE_MANAGER_ADDRESS
    POLYGON_CONTRACT_ADDRESS_V2      # the V2 registry
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv


def _abi(filename: str) -> list:
    path = Path(__file__).parent / filename
    if not path.exists():
        raise FileNotFoundError(f"ABI not found: {path}")
    return json.loads(path.read_text())


def _hash_to_bytes32(sha256_hex: str) -> bytes:
    clean = sha256_hex[2:] if sha256_hex.startswith("0x") else sha256_hex
    if len(clean) != 64:
        raise ValueError(f"Expected 64-char SHA-256 hex, got length {len(clean)}")
    return bytes.fromhex(clean)


def _make_w3(rpc_url: str):
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    try:
        from web3.middleware import ExtraDataToPOAMiddleware
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ImportError:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC: {rpc_url}")
    return w3


class MultiActorBackend:
    """Talks to the RoleManager + V2 CertificationRegistry for one pipeline."""

    name = "polygon-multiactor"

    def __init__(self, pipeline_id: int):
        load_dotenv()
        self.pipeline_id = int(pipeline_id)
        self.rpc_url = self._env("POLYGON_RPC_URL")
        self.role_manager_addr = self._env("ROLE_MANAGER_ADDRESS")
        self.registry_addr = self._env("POLYGON_CONTRACT_ADDRESS_V2")

        from web3 import Web3
        self.w3 = _make_w3(self.rpc_url)
        self.role_manager = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.role_manager_addr),
            abi=_abi("role_manager_abi.json"),
        )
        self.registry = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.registry_addr),
            abi=_abi("registry_v2_abi.json"),
        )

    @staticmethod
    def _env(name: str) -> str:
        v = os.getenv(name)
        if not v:
            raise RuntimeError(f"Missing environment variable: {name}")
        return v.strip()

    # ---- read-only checks --------------------------------------------------
    def can_certify(self, stage: str, actor_address: str) -> bool:
        """Ask the RoleManager whether this actor may certify this stage."""
        from web3 import Web3
        return self.role_manager.functions.canCertify(
            self.pipeline_id, stage, Web3.to_checksum_address(actor_address)
        ).call()

    def is_certified(self, manifest_sha256: str) -> bool:
        return self.registry.functions.isCertified(
            self.pipeline_id, _hash_to_bytes32(manifest_sha256)
        ).call()

    def parents_exist(self, parent_hashes: list) -> bool:
        """True only if every parent hash is already certified in this pipeline."""
        for h in parent_hashes:
            if not self.registry.functions.isCertified(
                self.pipeline_id, _hash_to_bytes32(h)
            ).call():
                return False
        return True

    # ---- state-changing ----------------------------------------------------
    def submit(self, actor_private_key: str, manifest_text: str,
               manifest_sha256: str) -> dict:
        """
        Actor signs and anchors the manifest hash for their stage.
        Fails fast if the actor is not authorized or a parent is missing --
        the same guarantees the contract enforces, checked early for a clear error.
        """
        from web3 import Web3

        account = self.w3.eth.account.from_key(actor_private_key)
        manifest = json.loads(manifest_text)
        stage = manifest.get("certificate_type", "unknown")
        parent_hashes = [p["manifest_sha256"]
                         for p in manifest.get("parent_certificates", [])]

        # Pre-flight checks for clear errors (contract enforces these too).
        if not self.can_certify(stage, account.address):
            raise PermissionError(
                f"Actor {account.address} is NOT authorized to certify "
                f"stage '{stage}' in pipeline {self.pipeline_id}."
            )
        if parent_hashes and not self.parents_exist(parent_hashes):
            raise RuntimeError("One or more parent certificates are missing on-chain.")

        manifest_hash = _hash_to_bytes32(manifest_sha256)
        parents_b32 = [_hash_to_bytes32(h) for h in parent_hashes]

        print(f"Actor: {account.address}")
        print(f"Pipeline: {self.pipeline_id}  |  Stage: {stage}  |  parents: {len(parents_b32)}")
        print("Submitting certificate to V2 registry...")

        tx = self.registry.functions.storeCertificate(
            self.pipeline_id, manifest_hash, stage, parents_b32
        ).build_transaction({
            "from": account.address,
            "nonce": self.w3.eth.get_transaction_count(account.address),
            "chainId": self.w3.eth.chain_id,
        })
        signed = account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"Transaction sent: {tx_hash.hex()}")

        rc = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if rc.status != 1:
            raise RuntimeError(f"Transaction failed on-chain: {tx_hash.hex()}")

        gas_price_wei = getattr(rc, "effectiveGasPrice", None) or self.w3.eth.gas_price
        cost_wei = rc.gasUsed * int(gas_price_wei)

        receipt = {
            "backend": self.name,
            "pipeline_id": self.pipeline_id,
            "manifest_sha256": manifest_sha256,
            "stage": stage,
            "network": os.getenv("POLYGON_NETWORK", "amoy"),
            "registry_address": self.registry.address,
            "role_manager_address": self.role_manager.address,
            "actor_address": account.address,
            "tx_id": tx_hash.hex(),
            "block_id": str(rc.blockNumber),
            "status": "Executed",
            "gas_used": rc.gasUsed,
            "gas_price_wei": int(gas_price_wei),
            "cost_wei": int(cost_wei),
            "cost_pol": float(Web3.from_wei(cost_wei, "ether")),
        }
        print(f"Status: Executed  |  gas: {rc.gasUsed}  |  cost: {receipt['cost_pol']:.8f} POL")
        return receipt
