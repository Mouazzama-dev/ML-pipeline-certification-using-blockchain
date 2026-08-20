#!/usr/bin/env python3
"""
estimate_cost_polygon.py
------------------------
Estimate the on-chain certification cost of each pipeline stage on Polygon,
from the transaction receipts saved by the Polygon backend.

Polygon (EVM) cost model:

    cost_POL = gas_used * gas_price
    cost_EUR = cost_POL * POL_EUR_RATE

Two cases are handled automatically per receipt:
  * New receipts store gas_price_wei (and cost_pol) -> exact cost is used.
  * Older receipts store only gas_used -> cost is estimated using --gas-price-gwei.

Usage:
    python estimate_cost_polygon.py \
        --receipts-dir certificates/receipts \
        --out-dir artifacts/metrics_polygon \
        --pol-eur-rate 0.40 \
        --gas-price-gwei 30
"""

import argparse
import csv
import glob
import json
import os

WEI_PER_POL = 10 ** 18
WEI_PER_GWEI = 10 ** 9

# Stage receipt files produced by the Polygon demo, in pipeline order.
STAGE_ORDER = ["dataset", "environment", "cleaning", "training", "model"]


def _stage_from_filename(path: str) -> str:
    name = os.path.basename(path).lower()
    for stage in STAGE_ORDER:
        if stage in name:
            return stage
    return "unknown"


def load_polygon_receipts(receipts_dir: str) -> list:
    """Load every receipt in the folder whose backend is 'polygon'."""
    receipts = []
    for path in sorted(glob.glob(os.path.join(receipts_dir, "*.json"))):
        try:
            data = json.load(open(path))
        except Exception:
            continue
        if data.get("backend") != "polygon":
            continue
        data["_stage"] = _stage_from_filename(path)
        data["_file"] = os.path.basename(path)
        receipts.append(data)
    # sort by pipeline order
    receipts.sort(key=lambda r: STAGE_ORDER.index(r["_stage"])
                  if r["_stage"] in STAGE_ORDER else 99)
    return receipts


def stage_cost(receipt: dict, fallback_gas_price_wei: int) -> dict:
    """Return the cost breakdown for one stage receipt."""
    gas_used = int(receipt.get("gas_used", 0))

    # Prefer the real gas price stored at submit time.
    gas_price_wei = receipt.get("gas_price_wei")
    exact = gas_price_wei is not None
    if not exact:
        gas_price_wei = fallback_gas_price_wei

    cost_wei = gas_used * int(gas_price_wei)
    cost_pol = cost_wei / WEI_PER_POL

    return {
        "gas_used": gas_used,
        "gas_price_gwei": round(int(gas_price_wei) / WEI_PER_GWEI, 4),
        "cost_pol": cost_pol,
        "source": "real" if exact else "estimated",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts-dir", default="certificates/receipts")
    ap.add_argument("--out-dir", default="artifacts/metrics_polygon")
    ap.add_argument("--pol-eur-rate", type=float, default=0.40,
                    help="POL price in EUR (check current rate).")
    ap.add_argument("--gas-price-gwei", type=float, default=30.0,
                    help="Fallback gas price for receipts that don't store one.")
    args = ap.parse_args()

    fallback_gas_price_wei = int(args.gas_price_gwei * WEI_PER_GWEI)

    receipts = load_polygon_receipts(args.receipts_dir)
    if not receipts:
        print(f"No Polygon receipts found in {args.receipts_dir}.")
        return

    os.makedirs(args.out_dir, exist_ok=True)

    rows = []
    total_gas = 0
    total_pol = 0.0
    for r in receipts:
        c = stage_cost(r, fallback_gas_price_wei)
        cost_eur = c["cost_pol"] * args.pol_eur_rate
        total_gas += c["gas_used"]
        total_pol += c["cost_pol"]
        rows.append({
            "stage": r["_stage"],
            "gas_used": c["gas_used"],
            "gas_price_gwei": c["gas_price_gwei"],
            "cost_pol": round(c["cost_pol"], 10),
            "cost_eur": round(cost_eur, 8),
            "cost_source": c["source"],
            "tx_id": r.get("tx_id", ""),
        })
        print(f"[{c['source']:9}] {r['_stage']:12} gas={c['gas_used']:>7}  "
              f"@ {c['gas_price_gwei']:>7} gwei  "
              f"= {c['cost_pol']:.8f} POL  (EUR {cost_eur:.6f})")

    total_eur = total_pol * args.pol_eur_rate

    # CSV
    csv_path = os.path.join(args.out_dir, "polygon_costs.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n" + "=" * 60)
    print(f"TOTAL gas: {total_gas}")
    print(f"TOTAL cost: {total_pol:.8f} POL  (EUR {total_eur:.6f})")
    print(f"POL->EUR rate used: {args.pol_eur_rate}")
    print("=" * 60)
    print(f"CSV written: {csv_path}")


if __name__ == "__main__":
    main()