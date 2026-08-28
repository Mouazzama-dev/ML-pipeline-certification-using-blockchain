#!/usr/bin/env bash
# ============================================================
# run_benchmark.sh  —  Blockchain Comparison Benchmark
# ============================================================
# Runs the complete Polygon Amoy pipeline N times (default 30)
# without interactive pauses, recording per-stage execution time
# and on-chain gas consumption for each run.
#
# Usage:
#   ./run_benchmark.sh [RUNS] [PIPELINE_ID]
#
# Examples:
#   ./run_benchmark.sh           # 30 runs, pipeline 1
#   ./run_benchmark.sh 5         # quick test with 5 runs
#   ./run_benchmark.sh 30 2      # 30 runs on pipeline #2
#
# Prerequisites:
#   • Python venv at .venv with all deps installed
#   • .env with BLOCKCHAIN=polygon + POLYGON_* RPC / wallet settings
#   • Funded Amoy wallet (each run submits 5 transactions)
#
# Outputs:
#   benchmark/polygon/results.csv    — per-run per-stage metrics
#   benchmark/polygon/summary.txt    — quick stats at the end
# ============================================================

set -uo pipefail

RUNS="${1:-30}"
PIPELINE_ID="${2:-1}"

# ── Environment ─────────────────────────────────────────────
source .venv/bin/activate
export BLOCKCHAIN=polygon
export PIPELINE_ID="$PIPELINE_ID"

BENCH_DIR="benchmark/polygon"
mkdir -p "$BENCH_DIR"

CSV="$BENCH_DIR/results.csv"
SUMMARY="$BENCH_DIR/summary.txt"

# Write CSV header only if the file is new
if [ ! -f "$CSV" ]; then
    echo "run,stage,duration_sec,gas_used,gas_price_gwei,cost_pol,tx_hash" > "$CSV"
fi

# ── Helpers ─────────────────────────────────────────────────

# Extract a scalar field from a Polygon JSON receipt
function jfield() {
python3 - "$1" "$2" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get(sys.argv[2], ""))
except Exception:
    print("")
PY
}

# Append one row to the results CSV
#   $1=run  $2=stage  $3=start_epoch_ns  $4=end_epoch_ns  $5=receipt_path
function log_stage() {
    local run="$1" stage="$2" t0="$3" t1="$4" rcpt="$5"
    local dur gas gwei cost_pol tx_hash

    dur=$(python3 -c "print(round(($t1-$t0)/1e9,2))")
    gas=$(jfield "$rcpt" "gas_used");  [ -z "$gas" ] && gas=0
    gwei=$(jfield "$rcpt" "gas_price_gwei"); [ -z "$gwei" ] && gwei=0
    cost_pol=$(jfield "$rcpt" "cost_pol"); [ -z "$cost_pol" ] && cost_pol=0
    tx_hash=$(jfield "$rcpt" "tx_id")

    echo "$run,$stage,$dur,$gas,$gwei,$cost_pol,$tx_hash" >> "$CSV"
    printf "    %-14s %6.1f s   gas=%7s   %.8f POL\n" \
           "$stage" "$dur" "$gas" "${cost_pol:-0}"
}

FAILED_RUNS=()

# ════════════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════════════
for run in $(seq 1 "$RUNS"); do

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Run $run / $RUNS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Track whether this run succeeded completely
    RUN_OK=true

    # ── STAGE 1: Dataset ────────────────────────────────────
    echo "  [1/5] Dataset"
    T0=$(date +%s%N)
    if python src/manifest_service.py \
          --type dataset \
          --output certificates/manifests/bench_dataset_manifest.json \
          --overwrite \
          --file dataset=data/raw/IRIS.csv \
          --meta note="benchmark" \
          --meta benchmark_run="$run" \
        && python src/certificate_service.py \
          --manifest certificates/manifests/bench_dataset_manifest.json \
          --receipt  certificates/receipts/bench_dataset_receipt.json \
        && python src/verify_certificate.py \
          --manifest certificates/manifests/bench_dataset_manifest.json \
          --receipt  certificates/receipts/bench_dataset_receipt.json
    then
        T1=$(date +%s%N)
        log_stage "$run" "dataset" "$T0" "$T1" \
                  "certificates/receipts/bench_dataset_receipt.json"
    else
        echo "  ✗ Dataset stage FAILED — skipping rest of run $run"
        RUN_OK=false
    fi

    if [ "$RUN_OK" != "true" ]; then FAILED_RUNS+=("$run"); continue; fi

    # ── STAGE 2: Environment ────────────────────────────────
    echo "  [2/5] Environment"
    T0=$(date +%s%N)
    if python src/environment_snapshot.py \
          --label "bench_env_run${run}" \
          --dependency-lock requirements.lock.txt \
          --output artifacts/environment/bench_environment.json \
          --overwrite \
        && python src/manifest_service.py \
          --type environment \
          --output certificates/manifests/bench_env_manifest.json \
          --overwrite \
          --file environment_snapshot=artifacts/environment/bench_environment.json \
          --file dependency_lock=requirements.lock.txt \
          --meta environment_version="bench_env_run${run}" \
          --meta benchmark_run="$run" \
        && python src/certificate_service.py \
          --manifest certificates/manifests/bench_env_manifest.json \
          --receipt  certificates/receipts/bench_env_receipt.json \
        && python src/verify_certificate.py \
          --manifest certificates/manifests/bench_env_manifest.json \
          --receipt  certificates/receipts/bench_env_receipt.json
    then
        T1=$(date +%s%N)
        log_stage "$run" "environment" "$T0" "$T1" \
                  "certificates/receipts/bench_env_receipt.json"
    else
        echo "  ✗ Environment stage FAILED — skipping rest of run $run"
        RUN_OK=false
    fi

    if [ "$RUN_OK" != "true" ]; then FAILED_RUNS+=("$run"); continue; fi

    # ── STAGE 3: Cleaning ───────────────────────────────────
    echo "  [3/5] Cleaning"
    T0=$(date +%s%N)
    if python src/clean_data.py --overwrite \
          --dataset-manifest     certificates/manifests/bench_dataset_manifest.json \
          --dataset-receipt      certificates/receipts/bench_dataset_receipt.json \
          --environment-manifest certificates/manifests/bench_env_manifest.json \
          --environment-receipt  certificates/receipts/bench_env_receipt.json \
        && python src/manifest_service.py \
          --type cleaning \
          --output certificates/manifests/bench_cleaning_manifest.json \
          --overwrite \
          --parent dataset=certificates/receipts/bench_dataset_receipt.json \
          --parent environment=certificates/receipts/bench_env_receipt.json \
          --file cleaning_script=src/clean_data.py \
          --file cleaned_dataset=data/processed/iris_cleaned.csv \
          --file cleaning_report=artifacts/logs/cleaning_report.json \
          --meta cleaning_version="bench_cleaning_run${run}" \
          --meta benchmark_run="$run" \
        && python src/certificate_service.py \
          --manifest certificates/manifests/bench_cleaning_manifest.json \
          --receipt  certificates/receipts/bench_cleaning_receipt.json \
        && python src/verify_certificate.py \
          --manifest certificates/manifests/bench_cleaning_manifest.json \
          --receipt  certificates/receipts/bench_cleaning_receipt.json
    then
        T1=$(date +%s%N)
        log_stage "$run" "cleaning" "$T0" "$T1" \
                  "certificates/receipts/bench_cleaning_receipt.json"
    else
        echo "  ✗ Cleaning stage FAILED — skipping rest of run $run"
        RUN_OK=false
    fi

    if [ "$RUN_OK" != "true" ]; then FAILED_RUNS+=("$run"); continue; fi

    # ── STAGE 4: Training ───────────────────────────────────
    echo "  [4/5] Training"
    T0=$(date +%s%N)
    if python src/train_model.py --overwrite \
          --cleaning-manifest certificates/manifests/bench_cleaning_manifest.json \
          --cleaning-receipt  certificates/receipts/bench_cleaning_receipt.json \
          --environment-manifest certificates/manifests/bench_env_manifest.json \
          --environment-receipt  certificates/receipts/bench_env_receipt.json \
        && python src/manifest_service.py \
          --type training \
          --output certificates/manifests/bench_training_manifest.json \
          --overwrite \
          --parent cleaning=certificates/receipts/bench_cleaning_receipt.json \
          --parent environment=certificates/receipts/bench_env_receipt.json \
          --file training_script=src/train_model.py \
          --file training_log=artifacts/logs/training_log.json \
          --meta training_version="bench_training_run${run}" \
          --meta benchmark_run="$run" \
        && python src/certificate_service.py \
          --manifest certificates/manifests/bench_training_manifest.json \
          --receipt  certificates/receipts/bench_training_receipt.json \
        && python src/verify_certificate.py \
          --manifest certificates/manifests/bench_training_manifest.json \
          --receipt  certificates/receipts/bench_training_receipt.json
    then
        T1=$(date +%s%N)
        log_stage "$run" "training" "$T0" "$T1" \
                  "certificates/receipts/bench_training_receipt.json"
    else
        echo "  ✗ Training stage FAILED — skipping rest of run $run"
        RUN_OK=false
    fi

    if [ "$RUN_OK" != "true" ]; then FAILED_RUNS+=("$run"); continue; fi

    # ── STAGE 5: Model ──────────────────────────────────────
    echo "  [5/5] Model"
    T0=$(date +%s%N)
    if python src/manifest_service.py \
          --type model \
          --output certificates/manifests/bench_model_manifest.json \
          --overwrite \
          --parent training=certificates/receipts/bench_training_receipt.json \
          --file model_artifact=artifacts/models/iris_nn_model.pkl \
          --meta model_version="bench_model_run${run}" \
          --meta benchmark_run="$run" \
        && python src/certificate_service.py \
          --manifest certificates/manifests/bench_model_manifest.json \
          --receipt  certificates/receipts/bench_model_receipt.json \
        && python src/verify_certificate.py \
          --manifest certificates/manifests/bench_model_manifest.json \
          --receipt  certificates/receipts/bench_model_receipt.json
    then
        T1=$(date +%s%N)
        log_stage "$run" "model" "$T0" "$T1" \
                  "certificates/receipts/bench_model_receipt.json"
    else
        echo "  ✗ Model stage FAILED"
        FAILED_RUNS+=("$run")
    fi

done

# ════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║           Benchmark complete                         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "Results CSV : $CSV"
if [ "${#FAILED_RUNS[@]}" -gt 0 ]; then
    echo "Failed runs : ${FAILED_RUNS[*]}"
fi

python3 - "$CSV" <<'PY'
import csv, sys, statistics

rows = list(csv.DictReader(open(sys.argv[1])))
stages = ["dataset","environment","cleaning","training","model"]

print(f"\n{'Stage':<14} {'N':>3}  {'Time mean':>10} {'Time std':>9}  "
      f"{'Gas mean':>10} {'Gas std':>9}  {'POL mean':>12}")
print("-" * 75)
for s in stages:
    sr = [r for r in rows if r["stage"] == s]
    if not sr:
        continue
    times  = [float(r["duration_sec"]) for r in sr]
    gases  = [int(r["gas_used"]) for r in sr if r["gas_used"]]
    costs  = [float(r["cost_pol"]) for r in sr if r["cost_pol"]]
    n = len(times)
    tmean = statistics.mean(times);  tstd = statistics.stdev(times) if n>1 else 0
    gmean = statistics.mean(gases) if gases else 0
    gstd  = statistics.stdev(gases) if len(gases)>1 else 0
    pmean = statistics.mean(costs) if costs else 0
    print(f"{s:<14} {n:>3}  {tmean:>9.1f}s {tstd:>8.1f}s  "
          f"{gmean:>10.0f} {gstd:>8.0f}  {pmean:>12.8f}")

print()
PY

echo "Run  python analyze_comparison.py  to generate charts and full comparison."
echo "Results saved to: $CSV"
