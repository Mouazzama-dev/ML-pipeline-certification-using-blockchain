#!/bin/bash
# chmod +x run_polygon_demo.sh
# ./run_polygon_demo.sh
#
# Full certified pipeline on the POLYGON backend, start to end.
# Submits every stage fresh (dataset -> environment -> cleaning -> training
# -> model) and records TIMING + GAS USED per stage.
#
# NOTE ON COST:
#   Only the 32-byte manifest hash goes on-chain, so there is no variable
#   "payload size" like Circular. The cost driver on Polygon is GAS. This
#   script records gas_used per stage; multiply by the gas price to get the
#   MATIC/POL cost. Requires .env with BLOCKCHAIN=polygon and the POLYGON_*
#   settings, plus a funded wallet on Amoy.

set -e

source .venv/bin/activate

# Force the Polygon backend regardless of what BLOCKCHAIN is in .env.
# (load_dotenv does not override an already-exported var.)
export BLOCKCHAIN=polygon

# =========================
# METRICS CONFIG
# =========================
RUN_ID=$(date +"%Y%m%d_%H%M%S")
METRICS_FILE="artifacts/metrics/polygon_pipeline_metrics_${RUN_ID}.csv"
mkdir -p artifacts/metrics

echo "stage,start_time,end_time,duration_sec,gas_used,block_id,tx_id,status" > "$METRICS_FILE"


# =========================
# HELPERS (ANALYSIS ONLY)
# =========================

# Pull a single field out of a Polygon receipt JSON (default 0 / empty).
function receipt_field() {
python - "$1" "$2" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    print(data.get(sys.argv[2], ""))
except Exception:
    print("")
PY
}

# Log timing + on-chain facts for one stage.
#   $1 = stage name   $2 = start epoch   $3 = end epoch   $4 = receipt file
function log_metrics() {
    local stage=$1 start=$2 end=$3 receipt=$4
    local duration=$((end - start))

    local gas block tx status
    gas=$(receipt_field "$receipt" gas_used)
    block=$(receipt_field "$receipt" block_id)
    tx=$(receipt_field "$receipt" tx_id)
    status=$(receipt_field "$receipt" status)
    [ -z "$gas" ] && gas=0

    echo "$stage,$start,$end,$duration,$gas,$block,$tx,$status" >> "$METRICS_FILE"
}


# =========================
# PIPELINE START
# =========================

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        Polygon Certification Pipeline - Start to End           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo


# ================================================================
# STEP 1: DATASET  (root cert, no parents)
# ================================================================
echo "=== STEP 1: Dataset Stage ==="
S1=$(date +%s)

python src/manifest_service.py \
  --type dataset \
  --output certificates/manifests/polygon_dataset_manifest.json \
  --overwrite \
  --file dataset=data/raw/IRIS.csv \
  --meta note="polygon full pipeline demo"

echo "📤 Submitting dataset certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/polygon_dataset_manifest.json \
  --receipt certificates/receipts/polygon_dataset_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/polygon_dataset_manifest.json \
  --receipt certificates/receipts/polygon_dataset_receipt.json

E1=$(date +%s)
log_metrics "dataset_stage" $S1 $E1 \
  "certificates/receipts/polygon_dataset_receipt.json"

read -p "Press Enter to continue to Environment stage..."


# ================================================================
# STEP 2: ENVIRONMENT  (root cert, no parents)
# ================================================================
echo
echo "=== STEP 2: Environment Stage ==="
S2=$(date +%s)

python src/environment_snapshot.py \
  --label environment_v1 \
  --dependency-lock requirements.lock.txt \
  --output artifacts/environment/polygon_environment_v1.json \
  --overwrite

python src/manifest_service.py \
  --type environment \
  --output certificates/manifests/polygon_environment_v1_manifest.json \
  --overwrite \
  --file environment_snapshot=artifacts/environment/polygon_environment_v1.json \
  --file dependency_lock=requirements.lock.txt \
  --meta environment_version=environment_v1

echo "📤 Submitting environment certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/polygon_environment_v1_manifest.json \
  --receipt certificates/receipts/polygon_environment_v1_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/polygon_environment_v1_manifest.json \
  --receipt certificates/receipts/polygon_environment_v1_receipt.json

E2=$(date +%s)
log_metrics "environment_stage" $S2 $E2 \
  "certificates/receipts/polygon_environment_v1_receipt.json"

read -p "Press Enter to continue to Cleaning stage..."


# ================================================================
# STEP 3: CLEANING  (parents: dataset, environment)
# ================================================================
echo
echo "=== STEP 3: Cleaning Stage ==="
S3=$(date +%s)

python src/clean_data.py --overwrite \
  --dataset-manifest certificates/manifests/polygon_dataset_manifest.json \
  --dataset-receipt certificates/receipts/polygon_dataset_receipt.json \
  --environment-manifest certificates/manifests/polygon_environment_v1_manifest.json \
  --environment-receipt certificates/receipts/polygon_environment_v1_receipt.json

python src/manifest_service.py \
  --type cleaning \
  --output certificates/manifests/polygon_cleaning_manifest.json \
  --overwrite \
  --parent dataset=certificates/receipts/polygon_dataset_receipt.json \
  --parent environment=certificates/receipts/polygon_environment_v1_receipt.json \
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
  --manifest certificates/manifests/polygon_cleaning_manifest.json \
  --receipt certificates/receipts/polygon_cleaning_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/polygon_cleaning_manifest.json \
  --receipt certificates/receipts/polygon_cleaning_receipt.json

E3=$(date +%s)
log_metrics "cleaning_stage" $S3 $E3 \
  "certificates/receipts/polygon_cleaning_receipt.json"

read -p "Press Enter to continue to Training stage..."


# ================================================================
# STEP 4: TRAINING  (parents: cleaning, environment)
# ================================================================
echo
echo "=== STEP 4: Training Stage ==="
S4=$(date +%s)

python src/train_model.py --overwrite \
  --cleaning-manifest certificates/manifests/polygon_cleaning_manifest.json \
  --cleaning-receipt certificates/receipts/polygon_cleaning_receipt.json \
  --environment-manifest certificates/manifests/polygon_environment_v1_manifest.json \
  --environment-receipt certificates/receipts/polygon_environment_v1_receipt.json

python src/manifest_service.py \
  --type training \
  --output certificates/manifests/polygon_training_manifest.json \
  --overwrite \
  --parent cleaning=certificates/receipts/polygon_cleaning_receipt.json \
  --parent environment=certificates/receipts/polygon_environment_v1_receipt.json \
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
  --manifest certificates/manifests/polygon_training_manifest.json \
  --receipt certificates/receipts/polygon_training_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/polygon_training_manifest.json \
  --receipt certificates/receipts/polygon_training_receipt.json

E4=$(date +%s)
log_metrics "training_stage" $S4 $E4 \
  "certificates/receipts/polygon_training_receipt.json"

read -p "Press Enter to continue to Model stage..."


# ================================================================
# STEP 5: MODEL  (parent: training)
# ================================================================
echo
echo "=== STEP 5: Model Stage ==="
S5=$(date +%s)

python src/manifest_service.py \
  --type model \
  --output certificates/manifests/polygon_model_manifest.json \
  --overwrite \
  --parent training=certificates/receipts/polygon_training_receipt.json \
  --file model_artifact=artifacts/models/iris_nn_model.pkl \
  --meta model_version=model_v3 \
  --meta model_type="MLPClassifier Neural Network" \
  --meta epochs=50 \
  --meta accuracy=0.5667

echo "📤 Submitting model certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/polygon_model_manifest.json \
  --receipt certificates/receipts/polygon_model_receipt.json

python src/verify_certificate.py \
  --manifest certificates/manifests/polygon_model_manifest.json \
  --receipt certificates/receipts/polygon_model_receipt.json

E5=$(date +%s)
log_metrics "model_stage" $S5 $E5 \
  "certificates/receipts/polygon_model_receipt.json"


# ================================================================
# DONE
# ================================================================
echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              ✅ POLYGON DEMO COMPLETE - ALL VERIFIED           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo
echo "📊 Timing + gas metrics saved to:"
echo "$METRICS_FILE"
echo
column -s, -t < "$METRICS_FILE"