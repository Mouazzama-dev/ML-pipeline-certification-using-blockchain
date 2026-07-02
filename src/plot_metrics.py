import os
import sys
import pandas as pd
import matplotlib.pyplot as plt


def main():
    if len(sys.argv) < 2:
        print("Usage: python src/plot_pipeline_metrics.py <metrics_csv_file>")
        sys.exit(1)

    metrics_file = sys.argv[1]

    if not os.path.exists(metrics_file):
        print(f"Metrics file not found: {metrics_file}")
        sys.exit(1)

    df = pd.read_csv(metrics_file)

    required_columns = [
        "stage",
        "duration_sec",
        "files_size_kb",
        "eur_cost"
    ]

    for col in required_columns:
        if col not in df.columns:
            print(f"Missing required column: {col}")
            sys.exit(1)

    df["cost_eur_per_kb"] = df["eur_cost"] / df["files_size_kb"]
    df["execution_time_sec_per_kb"] = df["duration_sec"] / df["files_size_kb"]

    output_dir = "artifacts/metrics/graphs"
    os.makedirs(output_dir, exist_ok=True)

    updated_csv = metrics_file.replace(".csv", "_with_ratios.csv")
    df.to_csv(updated_csv, index=False)

    print("Updated metrics with ratios saved to:")
    print(updated_csv)

    # Graph 1: Duration per stage
    plt.figure(figsize=(10, 6))
    plt.bar(df["stage"], df["duration_sec"])
    plt.title("Pipeline Execution Time by Stage")
    plt.xlabel("Stage")
    plt.ylabel("Duration Seconds")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/duration_by_stage.png", dpi=300)
    plt.close()

    # Graph 2: File size per stage
    plt.figure(figsize=(10, 6))
    plt.bar(df["stage"], df["files_size_kb"])
    plt.title("Output File Size by Stage")
    plt.xlabel("Stage")
    plt.ylabel("File Size KB")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/file_size_by_stage.png", dpi=300)
    plt.close()

    # Graph 3: EUR cost per stage
    plt.figure(figsize=(10, 6))
    plt.bar(df["stage"], df["eur_cost"])
    plt.title("Transaction Cost by Stage")
    plt.xlabel("Stage")
    plt.ylabel("Cost EUR")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/eur_cost_by_stage.png", dpi=300)
    plt.close()

    # Graph 4: Cost per KB
    plt.figure(figsize=(10, 6))
    plt.bar(df["stage"], df["cost_eur_per_kb"])
    plt.title("Transaction Cost per KB")
    plt.xlabel("Stage")
    plt.ylabel("EUR per KB")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/cost_eur_per_kb.png", dpi=300)
    plt.close()

    # Graph 5: Execution time per KB
    plt.figure(figsize=(10, 6))
    plt.bar(df["stage"], df["execution_time_sec_per_kb"])
    plt.title("Execution Time per KB")
    plt.xlabel("Stage")
    plt.ylabel("Seconds per KB")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(f"{output_dir}/execution_time_sec_per_kb.png", dpi=300)
    plt.close()

    print()
    print("Graphs saved in:")
    print(output_dir)
    print()
    print(df[[
        "stage",
        "duration_sec",
        "files_size_kb",
        "eur_cost",
        "cost_eur_per_kb",
        "execution_time_sec_per_kb"
    ]])


if __name__ == "__main__":
    main()