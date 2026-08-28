# Blockchain Comparison Benchmark — Tutorial

This tutorial guides you through running the automated benchmark that compares
**Polygon Amoy** and the **Circular Testnet** in certification cost and
execution time. The results are collected over 30 repetitions to report
mean values and standard deviations.

---

## What the Experiment Measures

| Metric | How it is measured |
|---|---|
| **Execution time** | Wall-clock time from the start to the end of each stage (manifest build + blockchain submission + on-chain confirmation) |
| **Gas used** | `gas_used` field from the Polygon Amoy transaction receipt |
| **Certification cost (Polygon)** | `gas_used × gas_price × POL/EUR rate` |
| **Certification cost (Circular)** | Deterministic formula from Section 9 of the report: `Total_CIRX = 11.5 + 2·n·(n+1)` applied to each stage's on-chain payload size |

> **Why is Circular cost analytical rather than a live run?**
> The Circular Testnet faucet was unavailable at the time of writing, so the
> pipeline cannot be re-executed.  The Circular fee function is deterministic:
> given the payload size, the exact charge can be computed without running a
> live transaction.  This is the same approach used in Section 9 of the report,
> where the estimates were verified to match every live receipt exactly.

---

## Prerequisites

1. **Python virtual environment** activated:

   ```bash
   source .venv/bin/activate
   pip install matplotlib numpy
   ```

2. **`.env` file** configured for Polygon Amoy (already used in development):

   ```bash
   BLOCKCHAIN=polygon
   POLYGON_RPC_URL=https://rpc-amoy.polygon.technology
   POLYGON_PRIVATE_KEY=<your_test_wallet_key>
   POLYGON_CHAIN_ID=80002
   PIPELINE_ID=1
   ```

3. **Funded Amoy wallet** — each run submits 5 transactions.  With 30 runs
   that is 150 transactions.  On Amoy, gas fees are negligible (fractions of
   a testnet MATIC), but the wallet must have some balance.
   Use the [Amoy faucet](https://faucet.polygon.technology/) to top up.

4. All five pipeline stages must already be able to run locally:
   - `data/raw/IRIS.csv` present
   - `requirements.lock.txt` present
   - `src/clean_data.py`, `src/train_model.py`, `src/manifest_service.py`,
     `src/certificate_service.py`, `src/verify_certificate.py` all working

---

## Step 1 — Quick Sanity Check (5 runs)

Before committing to 30 runs, verify the script works end-to-end with 5 runs:

```bash
chmod +x run_benchmark.sh
./run_benchmark.sh 5
```

Check that `benchmark/polygon/results.csv` contains 25 rows (5 runs × 5 stages)
and that gas values are non-zero.

---

## Step 2 — Full Benchmark (30 runs)

```bash
./run_benchmark.sh 30
```

**Expected duration:** approximately 3–5 minutes per run × 30 = 1.5–2.5 hours.
Run it in a terminal multiplexer (`tmux` or `screen`) so it can continue
unattended:

```bash
tmux new -s bench
./run_benchmark.sh 30
# Ctrl+B then D to detach; tmux attach -t bench to recheck
```

Progress is printed live.  Results are appended to
`benchmark/polygon/results.csv` after each stage, so partial runs are not lost.

---

## Step 3 — Analyse and Generate Charts

Once the benchmark finishes (or after any partial run), run the analysis script:

```bash
python analyze_comparison.py
```

Optional flags:

```bash
python analyze_comparison.py \
  --polygon-csv   benchmark/polygon/results.csv \
  --pol-eur-rate  0.40 \
  --gas-price-gwei 30
```

> **`--pol-eur-rate`** — check the current POL/EUR spot price (e.g. on
> CoinGecko) and set it here.  The default `0.40` is a conservative estimate
> for the Amoy testnet context.

The script outputs:

| File | Description |
|---|---|
| `benchmark/comparison_table.csv` | Full per-stage statistics table |
| `benchmark/comparison_exec_time.png` | Grouped bar chart: execution time |
| `benchmark/comparison_gas.png` | Gas used per stage (Polygon only) |
| `benchmark/comparison_cost_eur.png` | Certification cost in EUR |
| `benchmark/comparison_summary.txt` | Console-ready summary table |

---

## Step 4 — Interpreting the Results

### Execution time
Polygon Amoy time includes local computation **and** on-chain confirmation
wait.  Transaction confirmation on Amoy typically takes 5–30 seconds per
transaction.  The standard deviation across 30 runs reflects network
variability.

### Gas cost
Gas used per stage is nearly constant (same calldata → same EVM execution
path).  Cost variability comes from fluctuations in the gas price, which is
captured in the `gas_price_gwei` column of the results CSV.

### Circular Testnet cost
The Circular fee formula from the report gives an exact cost for each stage.
Because it is deterministic, the std dev is zero — this is expected and is
stated explicitly in the comparison table.

### Total pipeline cost
Add up all five stages for the end-to-end cost.  The report's Table 3 shows
the Circular total as **133.5 CIRX (≈ EUR 0.32)**.  The analysis script will
compute the Polygon total automatically from your 30 runs.

---

## File Reference

```
run_benchmark.sh          Automated 30-run Polygon pipeline benchmark
analyze_comparison.py     Statistical analysis and chart generation
TUTORIAL.md               This file

benchmark/
  polygon/
    results.csv           Raw per-run per-stage metrics
  comparison_table.csv    Side-by-side statistics (Polygon vs Circular)
  comparison_exec_time.png
  comparison_gas.png
  comparison_cost_eur.png
  comparison_summary.txt
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `No module named matplotlib` | Missing dependency | `pip install matplotlib numpy` |
| `Transaction reverted` | Wallet out of testnet MATIC | Top up from Amoy faucet |
| `ECONNREFUSED` on RPC | Wrong `POLYGON_RPC_URL` | Use a public Amoy RPC endpoint |
| Gas = 0 in CSV | Receipt not written correctly | Check `certificates/receipts/bench_*_receipt.json` |
| All times include huge spikes | Amoy network congestion | Re-run; exclude outliers manually in the CSV |

---

*Generated for the MSc Data Science internship report — University of Messina.*
*Supervisor: Prof. Maria Fazio / Danny De Novi.*
