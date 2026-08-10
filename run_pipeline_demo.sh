#!/bin/bash
# chmod +x run_pipeline_demo.sh
# ./run_pipeline_demo.sh
#
# This orchestration script runs the full certified pipeline and records
# TIMING and ON-CHAIN PAYLOAD SIZE for each stage.
#
# NOTE ON COST:
#   Blockchain certification COST is NOT computed here. Costs are estimated
#   separately with estimate_costs.py, which applies the Circular fee
#   function to each certificate's on-chain payload size. Keeping cost in a
#   single place (the estimator) avoids the two sources drifting apart and
#   lets costs be recomputed without re-running the pipeline or needing the
#   faucet.

set -e

source .venv/bin/activate

# =========================
# CONFIGURATION
# =========================
POLLING_INTERVAL=10
TIMEOUT_SEC=1200
MAX_POLLING_ROUNDS=120

# =========================
# METRICS CONFIG
# =========================
RUN_ID=$(date +"%Y%m%d_%H%M%S")
METRICS_FILE="artifacts/metrics/pipeline_metrics_${RUN_ID}.csv"
mkdir -p artifacts/metrics

echo "stage,start_time,end_time,duration_sec,payload_bytes,payload_kb" > "$METRICS_FILE"


# =========================
# HELPERS (ANALYSIS ONLY)
# =========================

# Return the on-chain payload size (in bytes) recorded in a receipt.
# The payload is a hex string, so byte size = len(hex)//2. It may live
# under outcome_response or transaction_response depending on the stage.
function get_payload_bytes() {
python - "$1" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    print(0); sys.exit(0)

payload = ""
for section in ("outcome_response", "transaction_response", "submission_response"):
    resp = data.get(section, {}).get("Response", {})
    p = resp.get("Payload", "")
    if p:
        payload = p
        break

print(len(payload) // 2)
PY
}

# Log timing + payload size for one stage.
#   $1 = stage name
#   $2 = start epoch
#   $3 = end epoch
#   $4 = receipt file (used only to read the on-chain payload size)
function log_metrics() {
    local stage=$1
    local start=$2
    local end=$3
    local receipt=$4

    local duration=$((end - start))

    local pbytes
    pbytes=$(get_payload_bytes "$receipt")
    if [ -z "$pbytes" ]; then pbytes=0; fi

    local pkb
    pkb=$(python -c "print(round($pbytes/1024, 3))")

    echo "$stage,$start,$end,$duration,$pbytes,$pkb" >> "$METRICS_FILE"
}


# =========================
# PIPELINE START
# =========================

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Blockchain Certification Pipeline - 20 Minute Timeout        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo


# ================================================================
# STEP 1: DATASET
# ================================================================
echo "=== STEP 1: Dataset Certificate Verification ==="
S1=$(date +%s)

python src/verify_certificate.py \
  --manifest certificates/manifests/dataset_manifest.json \
  --receipt certificates/receipts/dataset_receipt.json

E1=$(date +%s)

log_metrics "dataset_verification" $S1 $E1 \
  "certificates/receipts/dataset_receipt.json"

read -p "Press Enter to continue to Environment verification..."


# ================================================================
# STEP 2: ENVIRONMENT
# ================================================================
echo
echo "=== STEP 2: Environment Certificate Verification ==="
S2=$(date +%s)

python src/verify_certificate.py \
  --manifest certificates/manifests/environment_v1_manifest.json \
  --receipt certificates/receipts/environment_v1_receipt.json

E2=$(date +%s)

log_metrics "environment_verification" $S2 $E2 \
  "certificates/receipts/environment_v1_receipt.json"

read -p "Press Enter to continue to Cleaning stage..."


# ================================================================
# STEP 3: CLEANING
# ================================================================
echo
echo "=== STEP 3: Cleaning Stage ==="
S3=$(date +%s)

python src/clean_data.py --overwrite

python src/manifest_service.py \
  --type cleaning \
  --output certificates/manifests/cleaning_v3_manifest.json \
  --overwrite \
  --parent dataset=certificates/receipts/dataset_receipt.json \
  --parent environment=certificates/receipts/environment_v1_receipt.json \
  --file cleaning_script=src/clean_data.py \
  --file cleaned_dataset=data/processed/iris_cleaned.csv \
  --file cleaning_report=artifacts/logs/cleaning_report.json \
  --meta cleaning_version=cleaning_v3 \
  --meta input_rows=150 \
  --meta output_rows=147 \
  --meta duplicates_removed=3 \
  --meta missing_rows_removed=0

echo "📤 Submitting cleaning certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/cleaning_v3_manifest.json \
  --receipt certificates/receipts/cleaning_v3_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/cleaning_v3_manifest.json \
  --receipt certificates/receipts/cleaning_v3_receipt.json

E3=$(date +%s)

log_metrics "cleaning_stage" $S3 $E3 \
  "certificates/receipts/cleaning_v3_receipt.json"

read -p "Press Enter to continue to Training stage..."


# ================================================================
# STEP 4: TRAINING
# ================================================================
echo
echo "=== STEP 4: Training Stage ==="
S4=$(date +%s)

python src/train_model.py --overwrite

python src/manifest_service.py \
  --type training \
  --output certificates/manifests/training_v3_manifest.json \
  --overwrite \
  --parent cleaning=certificates/receipts/cleaning_v3_receipt.json \
  --parent environment=certificates/receipts/environment_v1_receipt.json \
  --file training_script=src/train_model.py \
  --file training_log=artifacts/logs/training_log.json \
  --meta training_version=training_v3 \
  --meta model_type="MLPClassifier Neural Network" \
  --meta epochs=50 \
  --meta hidden_layer_neurons=8 \
  --meta random_seed=42 \
  --meta accuracy=0.5667

echo "📤 Submitting training certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/training_v3_manifest.json \
  --receipt certificates/receipts/training_v3_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/training_v3_manifest.json \
  --receipt certificates/receipts/training_v3_receipt.json

E4=$(date +%s)

log_metrics "training_stage" $S4 $E4 \
  "certificates/receipts/training_v3_receipt.json"

read -p "Press Enter to continue to Model stage..."


# ================================================================
# STEP 5: MODEL
# ================================================================
echo
echo "=== STEP 5: Model Stage ==="
S5=$(date +%s)

python src/manifest_service.py \
  --type model \
  --output certificates/manifests/model_v3_manifest.json \
  --overwrite \
  --parent training=certificates/receipts/training_v3_receipt.json \
  --file model_artifact=artifacts/models/iris_nn_model.pkl \
  --meta model_version=model_v3 \
  --meta model_type="MLPClassifier Neural Network" \
  --meta epochs=50 \
  --meta accuracy=0.5667

echo "📤 Submitting model certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/model_v3_manifest.json \
  --receipt certificates/receipts/model_v3_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/model_v3_manifest.json \
  --receipt certificates/receipts/model_v3_receipt.json

E5=$(date +%s)

log_metrics "model_stage" $S5 $E5 \
  "certificates/receipts/model_v3_receipt.json"

# ================================================================
# DONE
# ================================================================
echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              ✅ DEMO COMPLETE - ALL VERIFIED                   ║"
echo "╚════════════════════════════════════════════════════════════════╝"

echo
echo "📊 Timing + payload metrics saved to:"
echo "$METRICS_FILE"
echo
echo "💰 To estimate certification cost from these receipts, run:"
echo "   python estimate_costs.py --receipts-dir certificates/receipts --out-dir artifacts/metrics_estimated"
echo

column -s, -t < "$METRICS_FILE"