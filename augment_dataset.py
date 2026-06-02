import argparse

import numpy as np

from dataset_utils import FEATURE_COLUMNS, TARGET_COLUMN, prepare_dataset


def augment_dataset(input_path, output_path, rows, noise, random_state):
    df, dataset_info = prepare_dataset(input_path)
    rng = np.random.default_rng(random_state)
    sampled = df.sample(n=rows, replace=True, random_state=random_state).reset_index(drop=True)

    for column in FEATURE_COLUMNS + [TARGET_COLUMN]:
        values = sampled[column].astype(float).to_numpy()
        variation = rng.normal(loc=1.0, scale=noise, size=len(sampled))
        sampled[column] = values * variation

    sampled["cpu_usage"] = sampled["cpu_usage"].clip(0, 100).round(2)
    sampled["memory_gb"] = sampled["memory_gb"].clip(lower=0).round(2)
    sampled["storage_gb"] = sampled["storage_gb"].clip(lower=0).round(2)
    sampled["bandwidth_gb"] = sampled["bandwidth_gb"].clip(lower=0).round(2)
    sampled["vm_count"] = sampled["vm_count"].round().clip(lower=1).astype(int)
    sampled[TARGET_COLUMN] = sampled[TARGET_COLUMN].clip(lower=0).round(6)
    sampled["dataset_source"] = "real_dataset_augmented"

    sampled.to_csv(output_path, index=False)
    print(f"Created {output_path} with {len(sampled)} rows.")
    print(f"Source dataset: {dataset_info['source_file']}")
    print("Use this only as an adapted/augmented dataset, not as a purely random dataset.")


def main():
    parser = argparse.ArgumentParser(description="Create a larger dataset by augmenting a real cloud dataset.")
    parser.add_argument("--input", default="Cloud_Dataset.csv", help="Input CSV dataset.")
    parser.add_argument("--output", default="Final_Cloud_Dataset.csv", help="Output augmented CSV dataset.")
    parser.add_argument("--rows", type=int, default=5000, help="Number of rows to create.")
    parser.add_argument("--noise", type=float, default=0.05, help="Variation level applied to sampled records.")
    parser.add_argument("--random-state", type=int, default=42, help="Reproducible random seed.")
    args = parser.parse_args()

    augment_dataset(args.input, args.output, args.rows, args.noise, args.random_state)


if __name__ == "__main__":
    main()
