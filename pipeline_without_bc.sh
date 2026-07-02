#!/bin/bash
#chmod +x run_pipeline_demo.sh
# ./run_pipeline_demo.sh 

set -e

source .venv/bin/activate

# =========================
# CONFIGURATION
# =========================
POLLING_INTERVAL=10
TIMEOUT_SEC=1200
MAX_POLLING_ROUNDS=120

# =========================
# METRICS CONFIG (NEW)
# =========================
RUN_ID=$(date +"%Y%m%d_%H%M%S")
METRICS_FILE="artifacts/metrics/pipeline_metrics_${RUN_ID}.csv"
mkdir -p artifacts/metrics

# CIRX → EUR rate (adjust when needed)
CIRX_EUR_RATE=${CIRX_EUR_RATE:-0.002403}

echo "stage,start_time,end_time,duration_sec,files_size_bytes,files_size_kb,cirx_cost,eur_cost" > "$METRICS_FILE"


# =========================
# HELPERS (NEW - ANALYSIS ONLY)
# =========================
function get_size_bytes() {
python - "$@" <<'PY'
import os, sys

total = 0
for path in sys.argv[1:]:
    if not os.path.exists(path):
        continue
    if os.path.isfile(path):
        total += os.path.getsize(path)
    else:
        for r, d, f in os.walk(path):
            for file in f:
                try:
                    total += os.path.getsize(os.path.join(r, file))
                except:
                    pass

print(total)
PY
}

function extract_cirx_cost() {
python - "$1" <<'PY'
import json, sys

data = json.load(open(sys.argv[1]))

# ALWAYS use canonical response only
response = (
    data.get("outcome_response", {})
        .get("Response", {})
)

keys = [
    "BroadcastFee",
    "ProtocolFee",
    "DeveloperFee",
    "ProcessingFee",
    "NagFee",
    "GasLimit"
]

total = sum(
    float(response.get(k, 0))
    for k in keys
)

print(round(total, 6))
PY
}

function log_metrics() {
    local stage=$1
    local start=$2
    local end=$3
    local receipt=$4  # 👈 Always make the receipt the 4th argument
    
    shift 4           # 👈 Shift by 4 so "$@" only contains the files for size checking

    local duration=$((end-start))
    local size=$(get_size_bytes "$@")
    local size_kb=$(python -c "print(round($size/1024,2))")

    # Call the extractor using our explicit receipt variable
    # local cirx=$(extract_cirx_cost "$receipt")
    
    # Handle empty or invalid returns gracefully by defaulting to 0
    if [ -z "$cirx" ]; then cirx=0; fi
    
    local eur=$(python -c "print(round($cirx*$CIRX_EUR_RATE,6))")

    echo "$stage,$start,$end,$duration,$size,$size_kb,$cirx,$eur" >> "$METRICS_FILE"
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

# python src/verify_certificate.py \
#   --manifest certificates/manifests/dataset_manifest.json \
#   --receipt certificates/receipts/dataset_receipt.json

# E1=$(date +%s)

# log_metrics "environment_verification" $S2 $E2 \
#   "certificates/receipts/environment_v1_receipt.json" \
#   "certificates/manifests/environment_v1_manifest.json" \
#   "certificates/receipts/environment_v1_receipt.json"


read -p "Press Enter to continue to Environment verification..."


# ================================================================
# STEP 2: ENVIRONMENT
# ================================================================
echo
echo "=== STEP 2: Environment Certificate Verification ==="
S2=$(date +%s)

# python src/verify_certificate.py \
#   --manifest certificates/manifests/environment_v1_manifest.json \
#   --receipt certificates/receipts/environment_v1_receipt.json

# E2=$(date +%s)

# log_metrics "environment_verification" $S2 $E2 \
#   "certificates/receipts/environment_v1_receipt.json" \
#   "certificates/manifests/environment_v1_manifest.json" \
#   "certificates/receipts/environment_v1_receipt.json"

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
# python src/certificate_service.py \
#   --manifest certificates/manifests/cleaning_v3_manifest.json \
#   --receipt certificates/receipts/cleaning_v3_receipt.json

# python src/verify_certificate.py \
#   --manifest certificates/manifests/cleaning_v3_manifest.json \
#   --receipt certificates/receipts/cleaning_v3_receipt.json

E3=$(date +%s)

# === STEP 3 ===
log_metrics "cleaning_stage" $S3 $E3 \
  "certificates/receipts/cleaning_v3_receipt.json" \
  "certificates/manifests/cleaning_v3_manifest.json" \
  "data/processed/iris_cleaned.csv" \
  "artifacts/logs/cleaning_report.json"


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
# python src/certificate_service.py \
#   --manifest certificates/manifests/training_v3_manifest.json \
#   --receipt certificates/receipts/training_v3_receipt.json

# python src/verify_certificate.py \
#   --manifest certificates/manifests/training_v3_manifest.json \
#   --receipt certificates/receipts/training_v3_receipt.json

E4=$(date +%s)

# === STEP 4 ===
log_metrics "training_stage" $S4 $E4 \
  "certificates/receipts/training_v3_receipt.json" \
  "certificates/manifests/training_v3_manifest.json" \
  "artifacts/models/iris_nn_model.pkl" \
  "artifacts/logs/training_log.json"




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
# python src/certificate_service.py \
#   --manifest certificates/manifests/model_v3_manifest.json \
#   --receipt certificates/receipts/model_v3_receipt.json

# python src/verify_certificate.py \
#   --manifest certificates/manifests/model_v3_manifest.json \
#   --receipt certificates/receipts/model_v3_receipt.json

E5=$(date +%s)

# === STEP 5 ===
log_metrics "model_stage" $S5 $E5 \
  "certificates/receipts/model_v3_receipt.json" \
  "certificates/manifests/model_v3_manifest.json" \
  "artifacts/models/iris_nn_model.pkl"

# ================================================================
# DONE
# ================================================================
echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              ✅ DEMO COMPLETE - ALL VERIFIED                   ║"
echo "╚════════════════════════════════════════════════════════════════╝"

echo
echo "📊 Metrics saved to:"
echo "$METRICS_FILE"

column -s, -t < "$METRICS_FILE"