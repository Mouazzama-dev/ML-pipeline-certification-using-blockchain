#!/usr/bin/env python3
"""
setup_pipeline_roles.py
-----------------------
One-time (per pipeline) admin script. Run by the pipeline OWNER/ADMIN.

It talks to the deployed RoleManager and:
  1. creates a new pipeline (admin becomes its owner),
  2. maps each role-gated stage to its required role,
  3. grants each actor their role for THIS pipeline.

Root stages (dataset, environment) are left with no role, so the admin (or any
actor) can certify them.

Reads from .env:
    POLYGON_RPC_URL
    POLYGON_PRIVATE_KEY        # ADMIN's key (must be the pipeline admin)
    ROLE_MANAGER_ADDRESS

Actor addresses are set below (edit to taste). After running, note the printed
pipelineId -- the stage services will need it.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

# ---- actor addresses for THIS pipeline (edit as needed) -------------------
PERSON_A = "0x73296D211A805362803aeCc9d181DF2585AfCA6F"  # DATA_CLEANER
PERSON_B = "0x83EF06a12F91A3a9a78C637E1dcb1034df67b966"  # MODEL_TRAINER
PERSON_C = "0xf59622D37998AF8087EAfD16E4271dFB80A4DdB9"  # REVIEWER

# ---- role tags (must match how services compute them) ---------------------
def role_tag(name: str) -> bytes:
    return Web3.keccak(text=name)

DATA_CLEANER  = role_tag("DATA_CLEANER")
MODEL_TRAINER = role_tag("MODEL_TRAINER")
REVIEWER      = role_tag("REVIEWER")

# stage -> role required to certify it. Root stages omitted (no role).
STAGE_ROLES = {
    "cleaning": DATA_CLEANER,
    "training": MODEL_TRAINER,
    "model":    REVIEWER,
}

# actor -> role granted
GRANTS = [
    (DATA_CLEANER,  PERSON_A),
    (MODEL_TRAINER, PERSON_B),
    (REVIEWER,      PERSON_C),
]


def load_role_manager_abi() -> list:
    """
    RoleManager ABI. Point this at the Foundry build output, or drop a copy
    next to this script as role_manager_abi.json.
    """
    candidates = [
        Path(__file__).parent / "role_manager_abi.json",
        Path("blockchain-contracts/out/RoleManager.sol/RoleManager.json"),
    ]
    for p in candidates:
        if p.exists():
            data = json.loads(p.read_text())
            # Foundry's artifact wraps abi under "abi"; a raw abi file is a list.
            return data["abi"] if isinstance(data, dict) and "abi" in data else data
    raise FileNotFoundError(
        "RoleManager ABI not found. Copy blockchain-contracts/out/RoleManager.sol/"
        "RoleManager.json next to this script as role_manager_abi.json, "
        "or run from the repo root."
    )


def send(w3, account, fn):
    """Build, sign, send a transaction and wait for it."""
    tx = fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"tx failed: {tx_hash.hex()}")
    return tx_hash.hex(), receipt


def main():
    load_dotenv()
    rpc = os.getenv("POLYGON_RPC_URL")
    key = os.getenv("POLYGON_PRIVATE_KEY")
    rm_addr = os.getenv("ROLE_MANAGER_ADDRESS")
    for name, val in [("POLYGON_RPC_URL", rpc), ("POLYGON_PRIVATE_KEY", key),
                      ("ROLE_MANAGER_ADDRESS", rm_addr)]:
        if not val:
            print(f"Missing env var: {name}", file=sys.stderr)
            sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(rpc))
    # PoA middleware for Polygon
    try:
        from web3.middleware import ExtraDataToPOAMiddleware
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ImportError:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    account = w3.eth.account.from_key(key)
    rm = w3.eth.contract(address=Web3.to_checksum_address(rm_addr),
                         abi=load_role_manager_abi())

    print(f"Admin: {account.address}")
    print(f"RoleManager: {rm_addr}\n")

    # 1. Create pipeline
    print("Creating pipeline...")
    _, receipt = send(w3, account, rm.functions.createPipeline())
    # pipelineId comes from the PipelineCreated event
    logs = rm.events.PipelineCreated().process_receipt(receipt)
    pipeline_id = logs[0]["args"]["pipelineId"]
    print(f"  Pipeline created: id = {pipeline_id}\n")

    # 2. Map stages to roles
    for stage, role in STAGE_ROLES.items():
        print(f"Setting stage role: {stage} -> {role.hex()[:10]}...")
        send(w3, account, rm.functions.setStageRole(pipeline_id, stage, role))

    # 3. Grant roles to actors
    print()
    for role, addr in GRANTS:
        addr_cs = Web3.to_checksum_address(addr)
        print(f"Granting {role.hex()[:10]}... to {addr_cs}")
        send(w3, account, rm.functions.grantRole(pipeline_id, role, addr_cs))

    print("\n" + "=" * 60)
    print(f"Pipeline {pipeline_id} is set up.")
    print("Actors:")
    print(f"  DATA_CLEANER  = {PERSON_A}")
    print(f"  MODEL_TRAINER = {PERSON_B}")
    print(f"  REVIEWER      = {PERSON_C}")
    print(f"\nRecord this pipelineId ({pipeline_id}) for the stage services.")
    print("=" * 60)


if __name__ == "__main__":
    main()
