import argparse
import json
import platform
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from hashing import hash_file
from verify_certificate import verify_certificate


FEATURE_COLUMNS = [
    "sepal_length",
    "sepal_width",
    "petal_length",
    "petal_width",
]

TARGET_COLUMN = "species"

EXPECTED_COLUMNS = FEATURE_COLUMNS + [TARGET_COLUMN]

RANDOM_SEED = 42
EPOCHS = 50
HIDDEN_LAYER_NEURONS = 8


def train_neural_network(
    input_path: str,
    model_output_path: str,
    log_output_path: str,
    overwrite: bool = False,
) -> None:
    model_file = Path(model_output_path)
    log_file = Path(log_output_path)

    if model_file.exists() and not overwrite:
        raise FileExistsError(
            f"Model output already exists: {model_output_path}. "
            "Do not overwrite a certified output."
        )

    if log_file.exists() and not overwrite:
        raise FileExistsError(
            f"Training log already exists: {log_output_path}. "
            "Do not overwrite a certified output."
        )

    print("--- Verifying Required Parent Certificates ---")

    cleaning_verified = verify_certificate(
        manifest_path="certificates/manifests/cleaning_v1_manifest.json",
        receipt_path="certificates/receipts/cleaning_v1_receipt.json",
        evidence_root=".",
    )

    if not cleaning_verified:
        raise RuntimeError("Cleaning Certificate verification failed. Training stopped.")

    environment_verified = verify_certificate(
        manifest_path="certificates/manifests/environment_v1_manifest.json",
        receipt_path="certificates/receipts/environment_v1_receipt.json",
        evidence_root=".",
    )

    if not environment_verified:
        raise RuntimeError("Environment Certificate verification failed. Training stopped.")

    print("\n--- Running Neural Network Training ---")

    df = pd.read_csv(input_path)

    if df.columns.tolist() != EXPECTED_COLUMNS:
        raise ValueError(
            f"Unexpected columns. Expected {EXPECTED_COLUMNS}, "
            f"but found {df.columns.tolist()}."
        )

    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=RANDOM_SEED,
        stratify=y,
    )

    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "neural_network",
                MLPClassifier(
                    hidden_layer_sizes=(HIDDEN_LAYER_NEURONS,),
                    activation="relu",
                    solver="adam",
                    max_iter=EPOCHS,
                    random_state=RANDOM_SEED,
                    shuffle=True,
                    learning_rate_init=0.001,
                ),
            ),
        ]
    )

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.perf_counter()

    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(X_train, y_train)

    elapsed_seconds = time.perf_counter() - start_time
    completed_at = datetime.now(timezone.utc).isoformat()

    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)

    neural_network = model.named_steps["neural_network"]

    epoch_losses = [
        {
            "epoch": index + 1,
            "loss": float(loss),
        }
        for index, loss in enumerate(neural_network.loss_curve_)
    ]

    convergence_warning_messages = [
        str(warning.message)
        for warning in captured_warnings
        if issubclass(warning.category, ConvergenceWarning)
    ]

    model_file.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_file)

    training_log = {
        "operation": "neural_network_training",
        "input_dataset": {
            "path": input_path,
            "sha256": hash_file(input_path),
            "rows": len(df),
        },
        "architecture": {
            "model_type": "Multi-Layer Perceptron Neural Network",
            "input_features": FEATURE_COLUMNS,
            "input_neurons": len(FEATURE_COLUMNS),
            "hidden_layers": [HIDDEN_LAYER_NEURONS],
            "hidden_activation": "relu",
            "output_classes": sorted(y.unique().tolist()),
            "output_neurons": int(y.nunique()),
        },
        "training_configuration": {
            "epochs_requested": EPOCHS,
            "epochs_completed": len(epoch_losses),
            "optimizer": "adam",
            "learning_rate_init": 0.001,
            "random_seed": RANDOM_SEED,
            "feature_scaling": "StandardScaler",
        },
        "data_split": {
            "test_size": 0.20,
            "stratified_by": TARGET_COLUMN,
            "training_rows": len(X_train),
            "testing_rows": len(X_test),
        },
        "epoch_losses": epoch_losses,
        "evaluation": {
            "accuracy": float(accuracy),
            "confusion_matrix": confusion_matrix(y_test, predictions).tolist(),
            "classification_report": classification_report(
                y_test,
                predictions,
                output_dict=True,
                zero_division=0,
            ),
        },
        "runtime": {
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "elapsed_seconds": elapsed_seconds,
            "python_version": platform.python_version(),
            "scikit_learn_version": sklearn.__version__,
            "machine": platform.machine(),
        },
        "warnings": convergence_warning_messages,
        "model_output_path": model_output_path,
    }

    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w", encoding="utf-8") as file:
        json.dump(training_log, file, indent=2, sort_keys=True)
        file.write("\n")

    print(f"Training rows: {len(X_train)}")
    print(f"Testing rows: {len(X_test)}")
    print(f"Epochs completed: {len(epoch_losses)}")

    for epoch_result in epoch_losses:
        print(
            f"Epoch {epoch_result['epoch']}: "
            f"loss = {epoch_result['loss']:.6f}"
        )

    print(f"Accuracy: {accuracy:.4f}")
    print(f"Training log saved: {log_output_path}")
    print(f"Model saved: {model_output_path}")
    print(f"Training log SHA-256: {hash_file(log_output_path)}")
    print(f"Model SHA-256: {hash_file(model_output_path)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify certified inputs and train an Iris neural network model."
    )

    parser.add_argument(
        "--input",
        default="data/processed/iris_cleaned.csv",
        help="Certified cleaned dataset path",
    )

    parser.add_argument(
        "--model-output",
        default="artifacts/models/iris_nn_model.pkl",
        help="Neural network model output path",
    )

    parser.add_argument(
        "--log-output",
        default="artifacts/logs/training_log.json",
        help="Training log output path",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite outputs only before blockchain certification",
    )

    args = parser.parse_args()

    try:
        train_neural_network(
            input_path=args.input,
            model_output_path=args.model_output,
            log_output_path=args.log_output,
            overwrite=args.overwrite,
        )
    except Exception as error:
        print(f"Training failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
