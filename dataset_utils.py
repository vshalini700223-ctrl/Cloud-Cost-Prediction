from pathlib import Path

import pandas as pd


TARGET_COLUMN = "cost"
FEATURES = [
    {
        "field": "cpu",
        "column": "cpu_usage",
        "label": "CPU usage",
        "unit": "%",
        "minimum": 0,
        "maximum": 100,
        "placeholder": "55",
        "aliases": ["cpu_usage", "cpu", "cpu_utilization", "cpu_percent", "CPU"],
    },
    {
        "field": "memory",
        "column": "memory_gb",
        "label": "Memory",
        "unit": "GB",
        "minimum": 0,
        "maximum": None,
        "placeholder": "2",
        "aliases": ["memory_gb", "RAM_GB", "ram_gb", "memory", "memory_usage", "Memory"],
    },
    {
        "field": "storage",
        "column": "storage_gb",
        "label": "Storage",
        "unit": "GB",
        "minimum": 0,
        "maximum": None,
        "placeholder": "460",
        "aliases": ["storage_gb", "storage", "storage_size", "storage_size_gb", "disk_gb", "disk_size", "disk_io"],
    },
    {
        "field": "bandwidth",
        "column": "bandwidth_gb",
        "label": "Bandwidth",
        "unit": "GB",
        "minimum": 0,
        "maximum": None,
        "placeholder": "420",
        "aliases": ["bandwidth_gb", "bandwidth", "network_bandwidth", "network_gb", "net_io", "network_io"],
    },
    {
        "field": "vms",
        "column": "vm_count",
        "label": "Virtual machines",
        "unit": "count",
        "minimum": 1,
        "maximum": None,
        "placeholder": "1",
        "aliases": ["vm_count", "vms", "vm", "number_of_vms", "instances", "instance_count", "vCPU"],
    },
]
FEATURE_COLUMNS = [feature["column"] for feature in FEATURES]
TARGET_ALIASES = ["cost", "cloud_cost", "total_cost", "price", "price_per_hour"]
OPTIONAL_COLUMNS = ["cloud_provider", "region", "vm_type", "RAM_GB", "vCPU", "utilization"]


def _find_column(df, aliases):
    lower_columns = {str(column).strip().lower(): column for column in df.columns}
    for alias in aliases:
        match = lower_columns.get(alias.lower())
        if match is not None:
            return match
    return None


def prepare_dataset(dataset_path):
    raw_df = pd.read_csv(dataset_path)
    prepared = pd.DataFrame()
    mappings = {}
    missing = []

    for feature in FEATURES:
        source_column = _find_column(raw_df, feature["aliases"])
        if source_column is None:
            missing.append({
                "feature": feature["label"],
                "accepted_columns": feature["aliases"],
            })
            continue
        prepared[feature["column"]] = pd.to_numeric(raw_df[source_column], errors="coerce")
        mappings[feature["column"]] = str(source_column)

    target_source = _find_column(raw_df, TARGET_ALIASES)
    if target_source is None:
        missing.append({
            "feature": "Cost target",
            "accepted_columns": TARGET_ALIASES,
        })
    else:
        prepared[TARGET_COLUMN] = pd.to_numeric(raw_df[target_source], errors="coerce")
        mappings[TARGET_COLUMN] = str(target_source)

    if missing:
        missing_text = "; ".join(
            f"{item['feature']} accepts one of {item['accepted_columns']}"
            for item in missing
        )
        raise ValueError(f"Dataset is missing required columns. {missing_text}")

    for column in OPTIONAL_COLUMNS:
        if column in raw_df.columns:
            prepared[column] = raw_df[column]

    prepared = prepared.dropna(subset=FEATURE_COLUMNS + [TARGET_COLUMN])
    if prepared.empty:
        raise ValueError("Dataset has no usable rows after cleaning numeric feature and cost values.")

    return prepared, {
        "source_file": str(Path(dataset_path).name),
        "column_mappings": mappings,
        "feature_definitions": FEATURES,
    }


def get_feature_ranges(df):
    ranges = {}
    for feature in FEATURES:
        column = feature["column"]
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        observed_min = round(float(series.min()), 4)
        observed_max = round(float(series.max()), 4)
        ranges[column] = {
            "minimum": feature["minimum"],
            "maximum": feature["maximum"] if feature["maximum"] is not None else observed_max,
            "observed_minimum": observed_min,
            "observed_maximum": observed_max,
        }
    return ranges
