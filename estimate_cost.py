#!/usr/bin/env python3
"""
estimate_costs.py
------------------
Estimates Circular Testnet certification cost for each pipeline stage
using the published Store-Certificate fee function, WITHOUT needing the
faucet or a live re-run.

Fee model (verified against live testnet receipts in this project):

    storage_kb   = ceil(on_chain_payload_bytes / 1024)          # n
    storage_cost = 2 * n * (n + 1)          CIRX   # triangular, base rate 4/KB
    fixed_fees   = NagFee(0.5) + BroadcastFee(1) + Minting_base(7) + Protocol_base(3)
                 = 11.5 CIRX
    total_cirx   = fixed_fees + storage_cost
    total_eur    = total_cirx * CIRX_EUR_RATE

The "storage" the chain bills for is the on-chain PAYLOAD (the encoded
certificate), NOT the local evidence-file size. Payload size is read
directly from each stage's receipt, so the estimate matches what the
network actually charged. Verified exact match on all five stages:
dataset 15.5, environment 23.5, cleaning 35.5, training 35.5, model 23.5 CIRX.

Usage:
    python estimate_costs.py \
        --receipts-dir certificates/receipts \
        --out-dir artifacts/metrics_estimated \
        --cirx-eur-rate 0.002403
"""

import argparse
import csv
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------
# Fee model constants (from Circular "Store Certificate" fee function,
# calibrated to this project's live testnet receipts)
# ----------------------------------------------------------------------
NAG_FEE = 0.5
BROADCAST_FEE = 1.0
MINTING_BASE = 7.0
PROTOCOL_BASE = 3.0
FIXED_FEES = NAG_FEE + BROADCAST_FEE + MINTING_BASE + PROTOCOL_BASE  # 11.5
STORAGE_RATE = 4.0  # CIRX for the 1st KB (calibrated); grows triangularly


# Stage display names + the receipt file for each (in pipeline order)
STAGES = [
    ("Dataset",     "dataset_receipt.json"),
    ("Environment", "environment_v1_receipt.json"),
    ("Cleaning",    "cleaning_v1_receipt.json"),
    ("Training",    "training_v1_receipt.json"),
    ("Model",       "model_v1_receipt.json"),
]


def storage_cost(n_kb: int) -> float:
    """Triangular storage cost: rate * n(n+1)/2, calibrated so 1 KB = 4 CIRX."""
    if n_kb <= 0:
        n_kb = 1
    return STORAGE_RATE * n_kb * (n_kb + 1) / 2.0


def get_payload_bytes(receipt: dict) -> int:
    """
    Return the on-chain payload size in bytes. The payload is a hex string,
    so byte size = len(hex)//2. It may live under outcome_response or, for
    some stages, transaction_response — check both.
    """
    for section in ("outcome_response", "transaction_response", "submission_response"):
        resp = receipt.get(section, {}).get("Response", {})
        payload = resp.get("Payload", "")
        if payload:
            return len(payload) // 2
    return 0


def estimate_stage(receipt_path: str):
    with open(receipt_path) as f:
        receipt = json.load(f)

    payload_bytes = get_payload_bytes(receipt)
    payload_kb = payload_bytes / 1024.0
    n_kb = math.ceil(payload_kb) if payload_kb > 0 else 1

    sc = storage_cost(n_kb)
    total_cirx = FIXED_FEES + sc

    return {
        "payload_bytes": payload_bytes,
        "payload_kb": round(payload_kb, 3),
        "billed_kb": n_kb,
        "storage_cost_cirx": round(sc, 3),
        "fixed_fees_cirx": FIXED_FEES,
        "total_cirx": round(total_cirx, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts-dir", default="certificates/receipts")
    ap.add_argument("--out-dir", default="artifacts/metrics_estimated")
    ap.add_argument("--cirx-eur-rate", type=float, default=0.002403)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    graphs_dir = os.path.join(args.out_dir, "graphs")
    os.makedirs(graphs_dir, exist_ok=True)

    rows = []
    for name, fn in STAGES:
        path = os.path.join(args.receipts_dir, fn)
        if not os.path.exists(path):
            print(f"[skip] {name}: receipt not found at {path}")
            continue
        est = estimate_stage(path)
        est["stage"] = name
        est["total_eur"] = round(est["total_cirx"] * args.cirx_eur_rate, 6)
        # cost efficiency
        kb = est["payload_kb"] if est["payload_kb"] > 0 else est["billed_kb"]
        est["eur_per_kb"] = round(est["total_eur"] / kb, 6) if kb else 0.0
        rows.append(est)
        print(f"[ok]   {name:12} payload={est['payload_bytes']:5d}B "
              f"billed={est['billed_kb']}KB  storage={est['storage_cost_cirx']:6.2f}  "
              f"total={est['total_cirx']:6.2f} CIRX  (EUR {est['total_eur']:.4f})")

    if not rows:
        print("No receipts processed. Check --receipts-dir.")
        return

    # ---- write CSV -----------------------------------------------------
    csv_path = os.path.join(args.out_dir, "estimated_costs.csv")
    fields = ["stage", "payload_bytes", "payload_kb", "billed_kb",
              "storage_cost_cirx", "fixed_fees_cirx", "total_cirx",
              "total_eur", "eur_per_kb"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\nCSV written: {csv_path}")

    # ---- write LaTeX table --------------------------------------------
    tex_path = os.path.join(args.out_dir, "estimated_costs_table.tex")
    with open(tex_path, "w") as f:
        f.write("\\begin{table}[h]\n\\centering\n")
        f.write("\\caption{Estimated Blockchain Certification Cost by Stage "
                "(Circular fee function, payload-based)}\n")
        f.write("\\begin{tabular}{lrrrrr}\n\\hline\n")
        f.write("Stage & Payload (B) & Billed KB & Storage (CIRX) & "
                "Total (CIRX) & Total (EUR) \\\\\n\\hline\n")
        for r in rows:
            f.write(f"{r['stage']} & {r['payload_bytes']} & {r['billed_kb']} & "
                    f"{r['storage_cost_cirx']:.1f} & {r['total_cirx']:.1f} & "
                    f"{r['total_eur']:.4f} \\\\\n")
        tot_cirx = sum(r["total_cirx"] for r in rows)
        tot_eur = sum(r["total_eur"] for r in rows)
        f.write("\\hline\n")
        f.write(f"\\textbf{{Total}} & & & & \\textbf{{{tot_cirx:.1f}}} & "
                f"\\textbf{{{tot_eur:.4f}}} \\\\\n")
        f.write("\\hline\n\\end{tabular}\n\\end{table}\n")
    print(f"LaTeX table written: {tex_path}")

    # ---- graphs --------------------------------------------------------
    stages = [r["stage"] for r in rows]

    def bar(values, title, ylabel, fname, color, fmt="{:.2f}"):
        plt.figure(figsize=(8, 5))
        bars = plt.bar(stages, values, color=color, edgecolor="black", linewidth=0.5)
        plt.title(title, fontsize=13, fontweight="bold")
        plt.ylabel(ylabel)
        plt.grid(axis="y", linestyle="--", alpha=0.4)
        for b, v in zip(bars, values):
            plt.text(b.get_x() + b.get_width()/2, b.get_height(),
                     fmt.format(v), ha="center", va="bottom", fontsize=9, fontweight="bold")
        plt.tight_layout()
        p = os.path.join(graphs_dir, fname)
        plt.savefig(p, dpi=150)
        plt.close()
        print(f"  graph: {p}")

    print("\nGenerating graphs:")
    bar([r["billed_kb"] for r in rows],
        "On-Chain Payload Size by Stage (Billed KB)",
        "Billed KB (payload)", "payload_size_by_stage.png", "#1f4e79", "{:.0f}")
    bar([r["total_cirx"] for r in rows],
        "Estimated Certification Cost by Stage",
        "Cost (CIRX)", "cost_cirx_by_stage.png", "#c0392b", "{:.1f}")
    bar([r["total_eur"] for r in rows],
        "Estimated Certification Cost by Stage (EUR)",
        "Cost (EUR)", "cost_eur_by_stage.png", "#b8860b", "\u20ac{:.4f}")
    bar([r["eur_per_kb"] for r in rows],
        "Cost Efficiency: EUR per KB of Payload",
        "EUR / KB", "eur_per_kb_by_stage.png", "#2e7d32", "\u20ac{:.4f}")

    # summary
    print("\n" + "="*60)
    print(f"TOTAL estimated cost: {sum(r['total_cirx'] for r in rows):.1f} CIRX  "
          f"(EUR {sum(r['total_eur'] for r in rows):.4f})")
    print(f"CIRX->EUR rate used: {args.cirx_eur_rate}")
    print("="*60)


if __name__ == "__main__":
    main()