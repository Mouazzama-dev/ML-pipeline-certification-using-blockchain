import argparse
import json
from pathlib import Path
import sys

import pandas as pd

from hashing import hash_file
from verify_certificate import verify_certificate

EXPECTED_COLUMNS = [
    "sepal_length",
    "sepal_width",
    "petal_length",
    "petal_width",
    "species"
]

EXPECTED_SPECIES = {"Iris-setosa", "Iris-versicolor", "Iris-virginica"}

def clean_dataset(
    input_path: str,
    output_path: str,
    report_path: str,
    overwrite: bool = False,
) -> None:
    output_file = Path(output_path)
    report_file = Path(report_path)

    if output_file.exists() and not overwrite:
        raise FileExistsError(
            f"Cleaned dataset already exists: {output_path}. "
            "Do not overwrite a certified output. Use --overwrite only before certification."
        )

    if report_file.exists() and not overwrite:
        raise FileExistsError(
            f"Cleaning report already exists: {report_path}. "
            "Do not overwrite a certified output. Use --overwrite only before certification."
        )

    print("--- Verifying Required Parent Certificates ---")

    dataset_verified = verify_certificate(
        manifest_path="certificates/manifests/dataset_manifest.json",
        receipt_path="certificates/receipts/dataset_receipt.json",
        evidence_root=".",
    )

    if not dataset_verified:
        raise RuntimeError("Dataset Certificate verification failed. Cleaning stopped.")

    environment_verified = verify_certificate(
        manifest_path="certificates/manifests/environment_v1_manifest.json",
        receipt_path="certificates/receipts/environment_v1_receipt.json",
        evidence_root=".",
    )

    if not environment_verified:
        raise RuntimeError("Environment Certificate verification failed. Cleaning stopped.")

    print("\n--- Running Deterministic Cleaning ---")

    raw_df = pd.read_csv(input_path)

    if raw_df.columns.tolist() != EXPECTED_COLUMNS:
        raise ValueError(
            f"Unexpected dataset columns. Expected {EXPECTED_COLUMNS}, "
            f"but found {raw_df.columns.tolist()}."
        )

    found_species = set(raw_df["species"].unique())

    if found_species != EXPECTED_SPECIES:
        raise ValueError(
            f"Unexpected species labels. Expected {EXPECTED_SPECIES}, "
            f"but found {found_species}."
        )

    input_rows = len(raw_df)
    missing_rows = int(raw_df.isnull().any(axis=1).sum())
    duplicate_rows = int(raw_df.duplicated().sum())

    cleaned_df = raw_df.dropna().drop_duplicates().reset_index(drop=True)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    cleaned_df.to_csv(output_file, index=False)

    report = {
        "operation": "deterministic_data_cleaning",
        "input_dataset": {
            "path": input_path,
            "sha256": hash_file(input_path),
            "rows": input_rows,
        },
        "output_dataset": {
            "path": output_path,
            "sha256": hash_file(output_path),
            "rows": len(cleaned_df),
        },
        "transformations": [
            "drop rows containing missing values",
            "drop duplicate rows",
            "reset row index",
        ],
        "results": {
            "missing_rows_removed": missing_rows,
            "duplicate_rows_removed": duplicate_rows,
            "total_rows_removed": input_rows - len(cleaned_df),
        },
        "columns": EXPECTED_COLUMNS,
        "class_distribution_after_cleaning": (
            cleaned_df["species"].value_counts().sort_index().to_dict()
        ),
    }

    report_file.parent.mkdir(parents=True, exist_ok=True)

    with report_file.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, sort_keys=True)
        file.write("\n")

    print(f"Input rows: {input_rows}")
    print(f"Missing rows removed: {missing_rows}")
    print(f"Duplicate rows removed: {duplicate_rows}")
    print(f"Output rows: {len(cleaned_df)}")
    print(f"Cleaned dataset saved: {output_path}")
    print(f"Cleaning report saved: {report_path}")
    print(f"Cleaned dataset SHA-256: {hash_file(output_path)}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify certified inputs and generate the cleaned Iris dataset."
    )

    parser.add_argument(
        "--input",
        default="data/raw/IRIS.csv",
        help="Raw input dataset path",
    )

    parser.add_argument(
        "--output",
        default="data/processed/iris_cleaned.csv",
        help="Cleaned dataset output path",
    )

    parser.add_argument(
        "--report",
        default="artifacts/logs/cleaning_report.json",
        help="Cleaning report output path",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite outputs only before blockchain certification",
    )

    args = parser.parse_args()

    try:
        clean_dataset(
            input_path=args.input,
            output_path=args.output,
            report_path=args.report,
            overwrite=args.overwrite,
        )
    except Exception as error:
        print(f"Cleaning failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


