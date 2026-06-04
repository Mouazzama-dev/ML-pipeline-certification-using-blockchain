#!/bin/bash
#chmod +x run_pipeline_demo.sh
# ./run_pipeline_demo.sh 

set -e

source .venv/bin/activate

# Configuration
POLLING_INTERVAL=10          # Check every 10 seconds
TIMEOUT_SEC=1200             # 20 minutes = 1200 seconds
MAX_POLLING_ROUNDS=120       # 1200 seconds / 10 seconds = 120 rounds

function wait_for_tx() {
    local manifest=$1
    local receipt=$2
    local txid=$3
    
    echo "⏳ Waiting for transaction to confirm: $txid"
    echo "   ⏱️  Timeout: 20 minutes | Poll interval: 10 seconds"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    python - "$txid" "$receipt" "$manifest" <<'PYEND'
import os, sys, json, time
from circular_enterprise_apis import CEP_Account
from dotenv import load_dotenv

load_dotenv(".env")

TX_ID = sys.argv[1]
RECEIPT_PATH = sys.argv[2]
MANIFEST_PATH = sys.argv[3]

account = CEP_Account()
account.set_network(os.environ["CIRCULAR_NETWORK"])
account.set_blockchain(os.environ["CIRCULAR_BLOCKCHAIN_ADDRESS"])

if not account.open(os.environ["CIRCULAR_WALLET_ADDRESS"]):
    raise RuntimeError(account.lastError)

try:
    timeout_sec = 1200      # 20 minutes
    poll_interval = 10      # 10 seconds
    max_rounds = 120        # 120 polling attempts
    
    start_time = time.time()
    round_num = 0
    
    while True:
        round_num += 1
        elapsed = time.time() - start_time
        remaining = timeout_sec - elapsed
        
        try:
            # FIX 1: Lowered SDK internal timeout to 2 seconds to avoid HTTP Timeout exceptions
            result = account.get_transaction_outcome(TX_ID, 2)
            
            response_data = result.get("Response", {})
            
            # FIX 2: Safely handle dictionary status versus string errors like "Transaction Not Found"
            if isinstance(response_data, dict):
                status = response_data.get("Status")
            else:
                status = str(response_data) # Handles "Transaction Not Found" text gracefully
            
            # Display status
            mins_elapsed = int(elapsed // 60)
            secs_elapsed = int(elapsed % 60)
            
            if status == "Executed":
                print(f"\n✅ SUCCESS! Transaction executed after {mins_elapsed}m {secs_elapsed}s")
                print(f"   TxID: {TX_ID}")
                
                # Save receipt
                with open(RECEIPT_PATH, "w") as f:
                    json.dump(result, f, indent=2)
                print(f"   Receipt saved: {RECEIPT_PATH}")
                break
                
            elif status == "Pending" or "Not Found" in status:
                # Treat "Transaction Not Found" identical to Pending status during initial node sync
                display_status = "Pending/Syncing" if "Not Found" in status else status
                progress = (round_num / 120) * 100
                bar_filled = int(progress / 5)
                bar_empty = 20 - bar_filled
                progress_bar = "█" * bar_filled + "░" * bar_empty
                
                print(f"\r[{progress_bar}] Round {round_num}/120 | {mins_elapsed}m {secs_elapsed}s / 20m | Status: {display_status}", end="", flush=True)
                
            else:
                print(f"\n⚠️  Status: {status} (Round {round_num})")
                
        except Exception as e:
            print(f"\n⚠️  Error checking status: {str(e)}")
            print(f"   Retrying... (Round {round_num}/120)")
        
        # Check timeout
        if elapsed > timeout_sec:
            print(f"\n❌ TIMEOUT: Transaction did not execute within 20 minutes")
            print(f"   TxID: {TX_ID}")
            print(f"   Elapsed: {mins_elapsed}m {secs_elapsed}s")
            sys.exit(1)
        
        # Check max rounds
        if round_num >= max_rounds:
            print(f"\n❌ MAX ROUNDS EXCEEDED: 120 polling attempts made")
            print(f"   Transaction may still be processing on the blockchain")
            sys.exit(1)
        
        # Wait before next poll
        time.sleep(poll_interval)

finally:
    account.close()
PYEND
}

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Blockchain Certification Pipeline - 20 Minute Timeout        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo

# STEP 1: Dataset
echo "=== STEP 1: Dataset Certificate Verification ==="
python src/verify_certificate.py \
  --manifest certificates/manifests/dataset_manifest.json \
  --receipt certificates/receipts/dataset_receipt.json
read -p "Press Enter to continue to Environment verification..."

# STEP 2: Environment
echo
echo "=== STEP 2: Environment Certificate Verification ==="
python src/verify_certificate.py \
  --manifest certificates/manifests/environment_v1_manifest.json \
  --receipt certificates/receipts/environment_v1_receipt.json
read -p "Press Enter to continue to Cleaning stage..."

# STEP 3: Cleaning
echo
echo "=== STEP 3: Cleaning Stage ==="
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

TXID_CLEANING=$(python -c "import json; print(json.load(open('certificates/manifests/cleaning_v3_manifest.json'))['parent_certificates'][0]['tx_id'])")
echo "📤 Submitting cleaning certificate..."
python src/certificate_service.py \
  --manifest certificates/manifests/cleaning_v3_manifest.json \
  --receipt certificates/receipts/cleaning_v3_receipt.json

# wait_for_tx certificates/manifests/cleaning_v3_manifest.json certificates/receipts/cleaning_v3_receipt.json "$TXID_CLEANING"
python src/verify_certificate.py \
  --manifest certificates/manifests/cleaning_v3_manifest.json \
  --receipt certificates/receipts/cleaning_v3_receipt.json
read -p "Press Enter to continue to Training stage..."

# STEP 4: Training
echo
echo "=== STEP 4: Training Stage ==="
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
read -p "Press Enter to continue to Model stage..."

# STEP 5: Model
echo
echo "=== STEP 5: Model Stage ==="
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

echo
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              ✅ DEMO COMPLETE - ALL VERIFIED                   ║"
echo "║     All blockchain transactions executed successfully           ║"
echo "╚════════════════════════════════════════════════════════════════╝"