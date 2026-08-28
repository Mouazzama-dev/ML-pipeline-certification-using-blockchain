#!/usr/bin/env python3
"""
analyze_comparison.py
---------------------
Reads the Polygon benchmark results (benchmark/polygon/results.csv) and
produces a statistical comparison between Polygon Amoy and the Circular
Testnet (whose costs are deterministic and computed analytically — see
Section 9 of the internship report).

Outputs:
    benchmark/comparison_table.csv
    benchmark/comparison_exec_time.png
    benchmark/comparison_gas_cost.png
    benchmark/comparison_cost_eur.png
    benchmark/comparison_summary.txt

Usage:
    python analyze_comparison.py
    python analyze_comparison.py --polygon-csv benchmark/polygon/results.csv \
                                 --pol-eur-rate 0.40 \
                                 --gas-price-gwei 30
"""

import argparse
import csv
import math
import os
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# CIRCULAR TESTNET  —  Deterministic cost model
# (from Section 9 of the internship report; verified against live receipts)
# ──────────────────────────────────────────────────────────────────────────────
# Fee formula:
#   Storage(n) = 4 * n*(n+1)/2  =  2*n*(n+1)   CIRX    (n = ceil(payload / 1024))
#   Total_CIRX = 11.5 + Storage(n)
#   Total_EUR  = Total_CIRX * CIRX_EUR_RATE

CIRX_EUR_RATE = 0.002403
FIXED_CIRX    = 11.5           # NAG + Broadcast + Minting_base + Protocol_base

# On-chain payload sizes measured from live receipts (bytes)
CIRCULAR_PAYLOAD = {
    "dataset":     794,
    "environment": 1476,
    "cleaning":    2952,
    "training":    2666,
    "model":       1666,
}

# Execution times measured during the original Circular Testnet run (seconds)
# Source: Figure 6 of the internship report; dataset estimated (not shown)
CIRCULAR_EXEC_S = {
    "dataset":      8.0,   # estimated — root cert, minimal local computation
    "environment": 13.0,
    "cleaning":    36.0,
    "training":    41.0,
    "model":       28.0,
}

STAGE_ORDER  = ["dataset", "environment", "cleaning", "training", "model"]
STAGE_LABELS = {
    "dataset": "Dataset",
    "environment": "Environment",
    "cleaning": "Cleaning",
    "training": "Training",
    "model": "Model",
}

WEI_PER_GWEI = 1e9
WEI_PER_POL  = 1e18


# ──────────────────────────────────────────────────────────────────────────────
# Cost helpers
# ──────────────────────────────────────────────────────────────────────────────

def cirx_cost(payload_bytes: int) -> float:
    n = math.ceil(payload_bytes / 1024)
    storage = 2 * n * (n + 1)
    return FIXED_CIRX + storage


def eur_from_cirx(cirx: float) -> float:
    return cirx * CIRX_EUR_RATE


def pol_cost(gas_used: int, gas_price_gwei: float) -> float:
    return gas_used * gas_price_gwei * WEI_PER_GWEI / WEI_PER_POL


# ──────────────────────────────────────────────────────────────────────────────
# Load Polygon benchmark results
# ──────────────────────────────────────────────────────────────────────────────

def load_polygon(csv_path: str, pol_eur_rate: float, fallback_gwei: float):
    by_stage = {s: {"time": [], "gas": [], "gwei": [], "pol": [], "eur": []}
                for s in STAGE_ORDER}

    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            stage = row.get("stage", "").strip()
            if stage not in by_stage:
                continue
            try:
                t    = float(row["duration_sec"])
                gas  = int(row["gas_used"]) if row.get("gas_used") else 0
                gwei = float(row["gas_price_gwei"]) if row.get("gas_price_gwei") else fallback_gwei
                cost_pol = float(row["cost_pol"]) if row.get("cost_pol") else pol_cost(gas, gwei)
                cost_eur = cost_pol * pol_eur_rate
            except (ValueError, KeyError):
                continue
            by_stage[stage]["time"].append(t)
            by_stage[stage]["gas"].append(gas)
            by_stage[stage]["gwei"].append(gwei)
            by_stage[stage]["pol"].append(cost_pol)
            by_stage[stage]["eur"].append(cost_eur)

    return by_stage


# ──────────────────────────────────────────────────────────────────────────────
# Statistics helpers
# ──────────────────────────────────────────────────────────────────────────────

def stats(values):
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    s = statistics.stdev(values) if len(values) > 1 else 0.0
    return m, s


# ──────────────────────────────────────────────────────────────────────────────
# Plotting
# ──────────────────────────────────────────────────────────────────────────────

PALETTE = {"polygon": "#7B3FE4", "circular": "#E47A3F"}

def _grouped_bar(labels, vals_a, errs_a, vals_b, errs_b,
                 label_a, label_b, ylabel, title, path, note=None):
    x     = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))

    ba = ax.bar(x - width/2, vals_a, width, yerr=errs_a, capsize=5,
                label=label_a, color=PALETTE["polygon"], alpha=0.85, error_kw={"elinewidth":1.5})
    bb = ax.bar(x + width/2, vals_b, width, yerr=errs_b, capsize=5,
                label=label_b, color=PALETTE["circular"], alpha=0.85, error_kw={"elinewidth":1.5})

    ax.set_title(title, fontsize=13, pad=12)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.legend(fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.3g"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    if note:
        ax.text(0.5, -0.13, note, transform=ax.transAxes,
                ha="center", fontsize=8, style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--polygon-csv",   default="benchmark/polygon/results.csv")
    ap.add_argument("--out-dir",       default="benchmark")
    ap.add_argument("--pol-eur-rate",  type=float, default=0.40,
                    help="Current POL/EUR exchange rate.")
    ap.add_argument("--gas-price-gwei",type=float, default=30.0,
                    help="Fallback gas price for receipts lacking gas_price_gwei.")
    args = ap.parse_args()

    if not os.path.exists(args.polygon_csv):
        sys.exit(f"ERROR: {args.polygon_csv} not found. Run run_benchmark.sh first.")

    os.makedirs(args.out_dir, exist_ok=True)

    # ── Load data ──────────────────────────────────────────────────────────────
    poly = load_polygon(args.polygon_csv, args.pol_eur_rate, args.gas_price_gwei)

    # ── Build per-stage comparison table ──────────────────────────────────────
    table_rows = []
    labels     = []
    p_time_m, p_time_s = [], []
    c_time_m, c_time_s = [], []
    p_gas_m,  p_gas_s  = [], []
    p_eur_m,  p_eur_s  = [], []
    c_eur_m,  c_eur_s  = [], []

    for stage in STAGE_ORDER:
        d = poly[stage]
        n = len(d["time"])
        if n == 0:
            print(f"  WARNING: no Polygon data for stage '{stage}' — skipping.")
            continue

        pt_m, pt_s = stats(d["time"])
        pg_m, pg_s = stats(d["gas"])
        pe_m, pe_s = stats(d["eur"])

        circ_cost_cirx = cirx_cost(CIRCULAR_PAYLOAD[stage])
        circ_cost_eur  = eur_from_cirx(circ_cost_cirx)
        ct_m = CIRCULAR_EXEC_S[stage]   # single historical measurement

        labels.append(STAGE_LABELS[stage])
        p_time_m.append(pt_m);   p_time_s.append(pt_s)
        c_time_m.append(ct_m);   c_time_s.append(0.0)   # historical, no std dev
        p_gas_m.append(pg_m);    p_gas_s.append(pg_s)
        p_eur_m.append(pe_m);    p_eur_s.append(pe_s)
        c_eur_m.append(circ_cost_eur);  c_eur_s.append(0.0)

        table_rows.append({
            "stage":                  STAGE_LABELS[stage],
            "n_runs":                 n,
            # Polygon
            "poly_time_mean_s":       round(pt_m, 2),
            "poly_time_std_s":        round(pt_s, 2),
            "poly_gas_mean":          round(pg_m, 0),
            "poly_gas_std":           round(pg_s, 0),
            "poly_cost_eur_mean":     round(pe_m, 6),
            "poly_cost_eur_std":      round(pe_s, 6),
            # Circular
            "circ_payload_bytes":     CIRCULAR_PAYLOAD[stage],
            "circ_cost_cirx":         round(circ_cost_cirx, 2),
            "circ_cost_eur":          round(circ_cost_eur, 6),
            "circ_time_s":            ct_m,
        })

    if not table_rows:
        sys.exit("No data found. Check that run_benchmark.sh produced output.")

    # ── CSV ────────────────────────────────────────────────────────────────────
    csv_path = os.path.join(args.out_dir, "comparison_table.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table_rows[0].keys()))
        w.writeheader(); w.writerows(table_rows)
    print(f"  Saved: {csv_path}")

    # ── Charts ─────────────────────────────────────────────────────────────────

    # 1. Execution time
    _grouped_bar(
        labels, p_time_m, p_time_s, c_time_m, c_time_s,
        "Polygon Amoy", "Circular Testnet",
        "Duration (seconds)", "End-to-End Stage Execution Time",
        os.path.join(args.out_dir, "comparison_exec_time.png"),
        note="Polygon: mean ± std dev over 30 runs.  "
             "Circular: single historical measurement (testnet unavailable for repetition)."
    )

    # 2. Gas used (Polygon only — Circular has no gas model)
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(labels))
    ax.bar(x, p_gas_m, yerr=p_gas_s, capsize=5,
           color=PALETTE["polygon"], alpha=0.85, error_kw={"elinewidth":1.5})
    ax.set_title("Gas Consumed per Stage  (Polygon Amoy)", fontsize=13, pad=12)
    ax.set_ylabel("Gas units", fontsize=11)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.text(0.5, -0.13, "Mean ± std dev over 30 runs.",
            transform=ax.transAxes, ha="center", fontsize=8,
            style="italic", color="#555")
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "comparison_gas.png"), dpi=150)
    plt.close(fig)
    print(f"  Saved: {os.path.join(args.out_dir, 'comparison_gas.png')}")

    # 3. Cost in EUR
    _grouped_bar(
        labels, p_eur_m, p_eur_s, c_eur_m, c_eur_s,
        "Polygon Amoy (POL→EUR)", "Circular Testnet (CIRX→EUR)",
        "Cost (EUR)", "Certification Cost per Stage",
        os.path.join(args.out_dir, "comparison_cost_eur.png"),
        note=f"Polygon: gas × gas_price × POL/EUR {args.pol_eur_rate:.2f}.  "
             f"Circular: deterministic formula; CIRX/EUR={CIRX_EUR_RATE}."
    )

    # ── Summary text ───────────────────────────────────────────────────────────
    summary_path = os.path.join(args.out_dir, "comparison_summary.txt")
    with open(summary_path, "w") as f:
        lines = [
            "=" * 70,
            "BLOCKCHAIN COMPARISON SUMMARY",
            f"Polygon Amoy  vs  Circular Testnet",
            f"Polygon runs: {table_rows[0]['n_runs']}",
            f"POL/EUR rate: {args.pol_eur_rate}",
            "=" * 70,
            "",
            "EXECUTION TIME (seconds)",
            f"  {'Stage':<14} {'Poly mean':>10} {'Poly std':>9}  {'Circ':>10}",
            "  " + "-" * 46,
        ]
        for r, ct in zip(table_rows, c_time_m):
            lines.append(f"  {r['stage']:<14} {r['poly_time_mean_s']:>10.1f}"
                         f" {r['poly_time_std_s']:>9.1f}  {ct:>10.1f}")

        poly_total_time  = sum(r["poly_time_mean_s"] for r in table_rows)
        circ_total_time  = sum(c_time_m)
        lines += [
            f"  {'TOTAL':<14} {poly_total_time:>10.1f}  {'':>9}  {circ_total_time:>10.1f}",
            "",
            "CERTIFICATION COST (EUR)",
            f"  {'Stage':<14} {'Poly mean':>12} {'Poly std':>11}  {'Circ':>12}",
            "  " + "-" * 52,
        ]
        for r in table_rows:
            lines.append(f"  {r['stage']:<14} €{r['poly_cost_eur_mean']:>11.6f}"
                         f" €{r['poly_cost_eur_std']:>10.6f}  €{r['circ_cost_eur']:>11.6f}")

        poly_total_eur  = sum(r["poly_cost_eur_mean"] for r in table_rows)
        circ_total_eur  = sum(r["circ_cost_eur"]      for r in table_rows)
        lines += [
            f"  {'TOTAL':<14} €{poly_total_eur:>11.6f}  {'':>11}  €{circ_total_eur:>11.6f}",
            "",
            "GAS USED (Polygon Amoy)",
            f"  {'Stage':<14} {'Gas mean':>10} {'Gas std':>9}",
            "  " + "-" * 35,
        ]
        for r in table_rows:
            lines.append(f"  {r['stage']:<14} {int(r['poly_gas_mean']):>10,}"
                         f" {int(r['poly_gas_std']):>9,}")
        poly_total_gas = sum(r["poly_gas_mean"] for r in table_rows)
        lines += [
            f"  {'TOTAL':<14} {int(poly_total_gas):>10,}",
            "",
            "NOTES",
            "  Circular cost is deterministic: same payload size → same fee.",
            "  Std dev for Circular cost = 0 (analytical formula, not a live run).",
            "  Circular execution time is from a single historical run (testnet",
            "  unavailable for repetition at time of writing).",
            "=" * 70,
        ]

        f.write("\n".join(lines) + "\n")

    print(f"  Saved: {summary_path}")

    # Print summary to stdout too
    print()
    with open(summary_path) as f:
        print(f.read())


if __name__ == "__main__":
    main()
