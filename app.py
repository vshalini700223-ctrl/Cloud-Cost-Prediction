import csv
import json
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request
import joblib
import pandas as pd

from dataset_utils import FEATURES, FEATURE_COLUMNS, TARGET_COLUMN, get_feature_ranges, prepare_dataset

app = Flask(__name__)

MODEL_PATH = Path("model.pkl")
METRICS_PATH = Path("model_metrics.json")
DATASET_PATH = Path("Cloud_Dataset.csv")
PREPARED_DATASET_PATH = Path("prepared_training_dataset.csv")
HISTORY_PATH = Path("prediction_history.csv")
DATASET_CONTEXT = None


def get_active_dataset_path():
    return PREPARED_DATASET_PATH if PREPARED_DATASET_PATH.exists() else DATASET_PATH


MODELS_DICT_PATH = Path("models.pkl")


def load_models():
    if MODELS_DICT_PATH.exists():
        try:
            loaded = joblib.load(MODELS_DICT_PATH)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass

    if MODEL_PATH.exists():
        try:
            single_model = joblib.load(MODEL_PATH)
            return {"Best Model": single_model}
        except Exception:
            pass

    return {}


models = load_models()


def get_best_model():
    metrics = load_metrics()
    if metrics and "best_model" in metrics:
        best_name = metrics["best_model"]
        if best_name in models:
            return models[best_name], best_name

    if models:
        first_key = list(models.keys())[0]
        return models[first_key], first_key
    return None, None


def load_metrics():
    if not METRICS_PATH.exists():
        return None
    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def load_dataset_context():
    # Load dynamically from model metrics if available to keep ranges and rows in sync with the trained model
    metrics = load_metrics()
    if metrics and "dataset" in metrics:
        ds = metrics["dataset"]
        ranges = {}
        feature_ranges = ds.get("feature_ranges", {})
        for feature in FEATURES:
            col = feature["column"]
            if col in feature_ranges:
                ranges[feature["field"]] = feature_ranges[col]
            else:
                ranges[feature["field"]] = {
                    "minimum": feature["minimum"],
                    "maximum": feature["maximum"] or 100.0,
                    "observed_minimum": feature["minimum"],
                    "observed_maximum": feature["maximum"] or 100.0,
                }
        return {
            "ranges": ranges,
            "rows": ds.get("rows", 0),
            "providers": ds.get("providers", []),
            "regions": ds.get("regions", []),
            "vm_types": ds.get("vm_types", []),
            "features": FEATURES,
            "column_mappings": ds.get("column_mappings", {}),
            "source_file": ds.get("source_file", ""),
        }

    # Fallback to direct dataset file loading if metrics don't exist yet
    default_ranges = {
        feature["field"]: {
            "minimum": feature["minimum"],
            "maximum": feature["maximum"] or 100.0,
            "observed_minimum": feature["minimum"],
            "observed_maximum": feature["maximum"] or 100.0,
        }
        for feature in FEATURES
    }
    context = {
        "ranges": default_ranges,
        "rows": 0,
        "providers": [],
        "regions": [],
        "vm_types": [],
        "features": FEATURES,
        "column_mappings": {},
        "source_file": "",
    }

    active_dataset_path = get_active_dataset_path()
    if not active_dataset_path.exists():
        return context

    try:
        df, dataset_info = prepare_dataset(active_dataset_path)
        feature_ranges = get_feature_ranges(df)
        ranges = {}
        for feature in FEATURES:
            ranges[feature["field"]] = feature_ranges[feature["column"]]

        return {
            "ranges": ranges,
            "rows": int(len(df)),
            "providers": sorted(df["cloud_provider"].dropna().unique().tolist()) if "cloud_provider" in df else [],
            "regions": sorted(df["region"].dropna().unique().tolist()) if "region" in df else [],
            "vm_types": sorted(df["vm_type"].dropna().unique().tolist()) if "vm_type" in df else [],
            "features": FEATURES,
            "column_mappings": dataset_info["column_mappings"],
            "source_file": dataset_info["source_file"],
        }
    except Exception:
        return context


def load_history(limit=12):
    if not HISTORY_PATH.exists():
        return []

    with open(HISTORY_PATH, "r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    return list(reversed(rows))[:limit]


def save_prediction(form, cost_summary, recommendations, budget_status):
    file_exists = HISTORY_PATH.exists()
    fieldnames = [
        "timestamp",
        *FEATURE_COLUMNS,
        "monthly_budget",
        "hourly_cost",
        "daily_cost",
        "monthly_cost",
        "budget_status",
        "recommendations",
    ]

    with open(HISTORY_PATH, "a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **{feature["column"]: form.get(feature["field"], "") for feature in FEATURES},
            "monthly_budget": form.get("budget", ""),
            "hourly_cost": cost_summary["hourly"],
            "daily_cost": cost_summary["daily"],
            "monthly_cost": cost_summary["monthly"],
            "budget_status": budget_status["status"] if budget_status else "",
            "recommendations": " | ".join(recommendations),
        })


def build_cost_summary(predicted_cost):
    hourly = round(predicted_cost, 4)
    return {
        "hourly": hourly,
        "daily": round(hourly * 24, 4),
        "monthly": round(hourly * 24 * 30, 4),
    }


def build_budget_status(form, monthly_cost):
    raw_budget = form.get("budget", "").strip()
    if not raw_budget:
        return None

    try:
        budget = float(raw_budget)
    except ValueError:
        return {
            "status": "Invalid budget",
            "message": "Monthly budget must be a number.",
            "is_over": False,
        }

    difference = round(monthly_cost - budget, 4)
    if difference > 0:
        return {
            "status": "Over budget",
            "message": f"Predicted monthly cost is ${difference} above your budget.",
            "is_over": True,
        }

    return {
        "status": "Within budget",
        "message": f"Predicted monthly cost is ${abs(difference)} within your budget.",
        "is_over": False,
    }


def generate_optimization_suggestions(form, monthly_cost, budget):
    suggestions = []

    try:
        cpu = float(form.get("cpu", 0))
        memory = float(form.get("memory", 0))
        storage = float(form.get("storage", 0))
        bandwidth = float(form.get("bandwidth", 0))
        vms = float(form.get("vms", 1))
    except ValueError:
        return ["Unable to generate suggestions due to invalid inputs."]

    # RULE 1: CPU Optimization
    if vms > 6:
        suggestions.append(
            f"Your VM/Server count is high (currently {int(vms)}). Consider reducing the active server count "
            f"(e.g., from {int(vms)} to 6) to lower compute costs. Reason: CPU allocation heavily impacts cloud cost."
        )
    elif cpu > 80:
        suggestions.append(
            f"High CPU utilization detected ({cpu}%). Consider optimizing code, implementing caching, "
            f"or using compute-optimized instance types to improve performance."
        )

    # RULE 2: RAM Optimization
    if memory > 16:
        suggestions.append(
            f"High memory allocation detected ({memory} GB). Consider memory optimization or "
            f"switching to memory-efficient instance types (e.g. memory-optimized VM families)."
        )

    # RULE 3: STORAGE Optimization
    if storage > 500:
        suggestions.append(
            f"High storage capacity requested ({storage} GB). Consider using data compression, "
            f"archiving cold data, or reducing the overall storage size."
        )

    # RULE 4: NETWORK Optimization
    if bandwidth > 300:
        suggestions.append(
            f"High network egress traffic ({bandwidth} GB). Consider reducing egress data, "
            f"optimizing traffic flow, or implementing caching/CDNs."
        )

    # RULE 5: COST vs BUDGET RULE
    if monthly_cost > budget:
        # Determine highest cost driver dynamically based on pricing coefficients:
        ram_cost = memory * 0.004
        storage_cost = storage * 0.00005
        bandwidth_cost = bandwidth * 0.0001
        cpu_cost = cpu * 0.0001

        drivers = [
            ("RAM capacity", ram_cost),
            ("Storage capacity", storage_cost),
            ("Network bandwidth", bandwidth_cost),
            ("CPU utilization", cpu_cost)
        ]
        highest_driver = max(drivers, key=lambda x: x[1])[0]

        suggestions.append(
            f"Predicted monthly cost (${monthly_cost:.2f}) exceeds your budget (${budget:.2f}). "
            f"We suggest: 1) reducing your highest-cost resource ({highest_driver}), "
            f"2) switching to a cheaper VM type, or 3) reducing your CPU/RAM balance."
        )

    return suggestions


def get_provider_comparison(form):
    active_dataset_path = get_active_dataset_path()
    if not active_dataset_path.exists():
        return []

    df, _ = prepare_dataset(active_dataset_path)
    required = {"cloud_provider", "region", "vm_type", "vm_count", TARGET_COLUMN}
    if not required.issubset(df.columns):
        return []

    vms = float(form.get("vms", 0))
    candidates = df[df["vm_count"] == vms]
    if candidates.empty:
        candidates = df

    grouped = (
        candidates
        .groupby(["cloud_provider", "region", "vm_type"], as_index=False)[TARGET_COLUMN]
        .mean()
        .sort_values(TARGET_COLUMN)
        .head(5)
    )

    comparisons = []
    for _, row in grouped.iterrows():
        hourly = round(float(row[TARGET_COLUMN]), 4)
        comparisons.append({
            "provider": row["cloud_provider"],
            "region": row["region"],
            "vm_type": row["vm_type"],
            "hourly": hourly,
            "monthly": round(hourly * 24 * 30, 4),
        })

    return comparisons


def parse_form(form):
    row = {}
    errors = []
    ranges = load_dataset_context()["ranges"]

    for feature in FEATURES:
        field_range = ranges.get(feature["field"], {})
        minimum = field_range.get("minimum", feature["minimum"])
        maximum = field_range.get("maximum", feature["maximum"])
        raw_value = form.get(feature["field"], "").strip()
        try:
            value = float(raw_value)
        except ValueError:
            errors.append(f"{feature['label']} must be a number.")
            continue

        if value < minimum:
            errors.append(f"{feature['label']} must be at least {minimum}.")

        row[feature["column"]] = value

    if errors:
        return None, errors

    return pd.DataFrame([row], columns=FEATURE_COLUMNS), errors


@app.route('/')
def home():
    return render_template("index.html", dataset_context=load_dataset_context())


@app.route('/dashboard')
def dashboard():
    metrics = load_metrics()
    return render_template(
        "dashboard.html",
        metrics=metrics,
        history=load_history(),
        dataset_context=load_dataset_context(),
    )


@app.route('/predict', methods=['POST'])
def predict():
    if not models:
        return render_template(
            "index.html",
            error="Model files not found. Run `python train_model.py` first.",
            form=request.form,
            dataset_context=load_dataset_context(),
        )

    data, errors = parse_form(request.form)
    if errors:
        return render_template(
            "index.html",
            errors=errors,
            form=request.form,
            dataset_context=load_dataset_context(),
        )

    # Get requested VM count
    vms = float(request.form.get("vms", 1))

    # Calculate predictions for all models
    predictions = {}
    best_model_obj, best_model_name = get_best_model()

    for name, m in models.items():
        data_unit = data.copy()
        if "vm_count" in data_unit.columns:
            data_unit["vm_count"] = 1.0

        pred_unit = float(m.predict(data_unit)[0])
        predictions[name] = round(pred_unit * vms, 4)

    # Primary predicted cost (from the best model)
    predicted_cost = predictions.get(best_model_name, list(predictions.values())[0] if predictions else 0.0)

    cost_summary = build_cost_summary(predicted_cost)
    provider_comparison = get_provider_comparison(request.form)

    # Check if budget is provided
    raw_budget = request.form.get("budget", "").strip()
    budget_status = None
    recommendations = []

    if raw_budget:
        try:
            budget_val = float(raw_budget)
            budget_status = build_budget_status(request.form, cost_summary["monthly"])
            recommendations = generate_optimization_suggestions(request.form, cost_summary["monthly"], budget_val)
        except ValueError:
            pass

    save_prediction(request.form, cost_summary, recommendations, budget_status)

    return render_template(
        "index.html",
        prediction=predicted_cost,
        cost_summary=cost_summary,
        recommendations=recommendations,
        vm_recommendation=None,
        budget_status=budget_status,
        provider_comparison=provider_comparison,
        model_predictions=predictions,
        best_model_name=best_model_name,
        form=request.form,
        dataset_context=load_dataset_context(),
    )


if __name__ == "__main__":
    app.run(debug=True)
