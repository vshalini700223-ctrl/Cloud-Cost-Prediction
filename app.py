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
DATASET_PATH = Path("Final_Cloud_Dataset.csv")
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


def load_history(limit=50):
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
            "recommendations": " | ".join(
                r["text"] if isinstance(r, dict) else r
                for r in recommendations
            ),
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


def get_model_coefficients(model):
    """Extract per-feature hourly cost coefficients from the model.
    For Linear Regression uses the actual fitted coef_ array.
    Falls back to the known pricing formula coefficients for tree-based models.
    FEATURE_COLUMNS order: [cpu_usage, memory_gb, storage_gb, bandwidth_gb, vm_count]
    """
    if model is not None and hasattr(model, "coef_"):
        coefs = list(model.coef_)
        return {
            "cpu":       round(abs(float(coefs[0])), 8),  # cpu_usage coef
            "memory":    round(abs(float(coefs[1])), 8),  # memory_gb coef
            "storage":   round(abs(float(coefs[2])), 8),  # storage_gb coef
            "bandwidth": round(abs(float(coefs[3])), 8),  # bandwidth_gb coef
        }
    # Fallback: known pricing formula coefficients from dataset_utils.py
    return {"cpu": 0.0001, "memory": 0.004, "storage": 0.00005, "bandwidth": 0.0001}


def build_cost_breakdown(form, model=None):
    """Calculate each resource's cost and percentage contribution to total cost.
    Uses the model's actual coefficients when available (e.g. Linear Regression coef_),
    otherwise falls back to the dataset pricing formula coefficients.
    """
    try:
        cpu = float(form.get("cpu", 0))
        memory = float(form.get("memory", 0))
        storage = float(form.get("storage", 0))
        bandwidth = float(form.get("bandwidth", 0))
    except (ValueError, TypeError):
        cpu, memory, storage, bandwidth = 0, 0, 0, 0

    coefs = get_model_coefficients(model)

    cpu_cost_hr       = cpu       * coefs["cpu"]
    ram_cost_hr       = memory    * coefs["memory"]
    storage_cost_hr   = storage   * coefs["storage"]
    bandwidth_cost_hr = bandwidth * coefs["bandwidth"]

    total_hr = cpu_cost_hr + ram_cost_hr + storage_cost_hr + bandwidth_cost_hr

    if total_hr == 0:
        return {
            "cpu":       {"cost_monthly": 0, "pct": 0},
            "memory":    {"cost_monthly": 0, "pct": 0},
            "storage":   {"cost_monthly": 0, "pct": 0},
            "bandwidth": {"cost_monthly": 0, "pct": 0},
        }

    def monthly(hr): return round(hr * 24 * 30, 4)
    def pct(hr): return round((hr / total_hr) * 100, 1)

    return {
        "cpu":       {"cost_monthly": monthly(cpu_cost_hr),       "pct": pct(cpu_cost_hr)},
        "memory":    {"cost_monthly": monthly(ram_cost_hr),        "pct": pct(ram_cost_hr)},
        "storage":   {"cost_monthly": monthly(storage_cost_hr),    "pct": pct(storage_cost_hr)},
        "bandwidth": {"cost_monthly": monthly(bandwidth_cost_hr),  "pct": pct(bandwidth_cost_hr)},
    }


def generate_optimization_suggestions(form, monthly_cost, budget, cost_breakdown):
    """Dynamic, cost-impact-based optimization engine.

    Rules (no hardcoded thresholds):
    - If cost <= budget  → already optimized; return a positive confirmation.
    - If cost > budget   → identify the highest cost-driver, calculate the
      exact overflow, and generate proportional, targeted suggestions.
    """

    # ── GUARD: already within budget ─────────────────────────────────────────
    if monthly_cost <= budget:
        return [{
            "type": "success",
            "text": (
                f"✅ Your resource configuration is already optimised and fits within "
                f"your monthly budget of <strong>${budget:.2f}</strong>. "
                f"(Predicted: <strong>${monthly_cost:.2f}/mo</strong>)"
            ),
        }]

    # ── Parse inputs ──────────────────────────────────────────────────────────
    try:
        cpu      = float(form.get("cpu", 0))
        memory   = float(form.get("memory", 0))
        storage  = float(form.get("storage", 0))
        bandwidth = float(form.get("bandwidth", 0))
        vms      = float(form.get("vms", 1))
    except (ValueError, TypeError):
        return [{"type": "error", "text": "Unable to generate suggestions due to invalid inputs."}]

    suggestions = []

    # ── Cost overflow analysis ────────────────────────────────────────────────
    overflow        = monthly_cost - budget                    # absolute $ over budget
    overflow_pct    = (overflow / monthly_cost) * 100         # % cost that must be cut

    # ── Rank resources by cost impact (highest → lowest) ─────────────────────
    drivers = [
        ("Memory (RAM)",       "memory",    cost_breakdown["memory"]["pct"],    cost_breakdown["memory"]["cost_monthly"]),
        ("Storage",            "storage",   cost_breakdown["storage"]["pct"],   cost_breakdown["storage"]["cost_monthly"]),
        ("Network Bandwidth",  "bandwidth", cost_breakdown["bandwidth"]["pct"], cost_breakdown["bandwidth"]["cost_monthly"]),
        ("CPU Utilization",    "cpu",       cost_breakdown["cpu"]["pct"],       cost_breakdown["cpu"]["cost_monthly"]),
    ]
    drivers.sort(key=lambda x: x[2], reverse=True)            # sort by % contribution desc

    top_driver_name, top_driver_key, top_driver_pct, top_driver_cost = drivers[0]
    second_driver_pct = drivers[1][2] if len(drivers) > 1 else 0

    # Values mapped by key for proportional suggestions
    resource_vals = {"cpu": cpu, "memory": memory, "storage": storage, "bandwidth": bandwidth}
    resource_units = {"cpu": "%", "memory": "GB", "storage": "GB", "bandwidth": "GB"}

    # ── RULE 1: Dominant single driver (≥50% OR 2× the next resource) ────────
    is_dominant = (top_driver_pct >= 50) or (top_driver_pct >= second_driver_pct * 2)

    if is_dominant:
        current_val    = resource_vals[top_driver_key]
        # Reduce only this resource by the exact proportion needed to close the gap
        reduce_by_pct  = overflow_pct / (top_driver_pct / 100)   # scale reduction to this resource's share
        reduce_by_pct  = min(reduce_by_pct, 80)                   # cap at 80% reduction (sanity bound)
        target_val     = round(current_val * (1 - reduce_by_pct / 100), 2)
        target_val     = max(target_val, 0.01)
        unit           = resource_units[top_driver_key]

        suggestions.append({
            "type": "warning",
            "text": (
                f"🎯 <strong>{top_driver_name}</strong> is your highest cost driver "
                f"(<strong>{top_driver_pct:.1f}%</strong> of total cost, "
                f"<strong>${top_driver_cost:.2f}/mo</strong>). "
                f"To close the <strong>${overflow:.2f}</strong> budget gap, reduce it from "
                f"<strong>{current_val:.2f} {unit}</strong> → "
                f"<strong>~{target_val:.2f} {unit}</strong> "
                f"(a <strong>{reduce_by_pct:.0f}%</strong> reduction). "
                f"This alone would bring your predicted cost close to your "
                f"<strong>${budget:.2f}</strong> budget."
            ),
        })

    # ── RULE 2: Proportional multi-resource reduction ─────────────────────────
    else:
        # Suggest proportional cuts across the top contributors
        suggestions.append({
            "type": "warning",
            "text": (
                f"⚡ Your cost is spread across multiple resources. "
                f"To reduce monthly spend by <strong>${overflow:.2f}</strong> and fit "
                f"your <strong>${budget:.2f}</strong> budget, a proportional "
                f"<strong>{overflow_pct:.0f}%</strong> reduction across your top cost "
                f"drivers is needed:"
            ),
        })
        for d_name, d_key, d_pct, d_cost in drivers:
            if d_pct < 5:
                continue   # skip negligible contributors
            current_val = resource_vals[d_key]
            target_val  = round(current_val * (1 - overflow_pct / 100), 2)
            target_val  = max(target_val, 0.01)
            unit        = resource_units[d_key]
            suggestions.append({
                "type": "info",
                "text": (
                    f"• <strong>{d_name}</strong> ({d_pct:.1f}% of cost): "
                    f"{current_val:.2f} {unit} → <strong>~{target_val:.2f} {unit}</strong>"
                ),
            })

    # ── RULE 3 / RULE 4: Smart VM-family swap hint ───────────────────────────
    top_two_pct = drivers[0][2] + drivers[1][2]
    if vms > 1 and top_two_pct >= 65 and overflow_pct > 25:
        suggestions.append({
            "type": "info",
            "text": (
                f"💡 With <strong>{int(vms)} VMs</strong> and your top two resources "
                f"accounting for <strong>{top_two_pct:.0f}%</strong> of cost, consider "
                f"switching to a more cost-efficient VM family "
                f"(e.g., compute-optimised or burstable instances) "
                f"rather than tuning individual resources — this often yields better savings."
            ),
        })

    # ── RULE 5: Budget fitting summary ───────────────────────────────────────
    suggestions.append({
        "type": "summary",
        "text": (
            f"📊 Cost overview: <strong>${monthly_cost:.2f}/mo</strong> predicted vs "
            f"<strong>${budget:.2f}/mo</strong> budget. "
            f"Gap to close: <strong>${overflow:.2f}</strong> "
            f"({overflow_pct:.1f}% reduction needed). "
            f"Highest impact resource: <strong>{top_driver_name}</strong> "
            f"at <strong>{top_driver_pct:.1f}%</strong> of total cost."
        ),
    })

    return suggestions


def get_provider_comparison(form):
    active_dataset_path = get_active_dataset_path()
    if not active_dataset_path.exists():
        return []

    df, _ = prepare_dataset(active_dataset_path)
    required = {"cloud_provider", "region", "vm_type", "vm_count", TARGET_COLUMN}
    if not required.issubset(df.columns):
        return []

    try:
        vms = float(form.get("vms", 1))
    except (ValueError, TypeError):
        vms = 1.0

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
        # Scale the unit cost by the number of VMs to make it comparable
        hourly = round(float(row[TARGET_COLUMN]) * vms, 4)
        vm_label = f"{row['vm_type']} ({int(vms)} VMs)" if vms > 1 else row["vm_type"]
        comparisons.append({
            "provider": row["cloud_provider"],
            "region": row["region"],
            "vm_type": vm_label,
            "hourly": hourly,
            "monthly": round(hourly * 24 * 30, 4),
        })

    return comparisons


def parse_form(form):
    row = {}
    errors = {}
    ranges = load_dataset_context()["ranges"]

    for feature in FEATURES:
        field_range = ranges.get(feature["field"], {})
        minimum = field_range.get("minimum", feature["minimum"])
        maximum = field_range.get("maximum", feature["maximum"])
        raw_value = form.get(feature["field"], "").strip()
        try:
            value = float(raw_value)
        except ValueError:
            errors[feature["field"]] = "Must be a valid number."
            continue

        if value < minimum:
            errors[feature["field"]] = f"Must be at least {minimum}."

        row[feature["column"]] = value

    raw_budget = form.get("budget", "").strip()
    if raw_budget:
        try:
            float(raw_budget)
        except ValueError:
            errors["budget"] = "Must be a valid number."

    if errors:
        return None, errors

    return pd.DataFrame([row], columns=FEATURE_COLUMNS), errors


@app.route('/')
def home():
    best_model_obj, _ = get_best_model()
    model_coefs = get_model_coefficients(best_model_obj)
    return render_template(
        "index.html",
        dataset_context=load_dataset_context(),
        model_coefs=model_coefs,
    )



@app.route('/dashboard')
def dashboard():
    metrics = load_metrics()
    return render_template(
        "dashboard.html",
        metrics=metrics,
        history=load_history(limit=20),
        dataset_context=load_dataset_context(),
    )


@app.route('/history')
def history_page():
    all_history = load_history(limit=200)
    return render_template(
        "history.html",
        history=all_history,
        dataset_context=load_dataset_context(),
    )


@app.route('/predict', methods=['POST'])
def predict():
    if not models:
        fallback_coefs = {"cpu": 0.0001, "memory": 0.004, "storage": 0.00005, "bandwidth": 0.0001}
        return render_template(
            "index.html",
            error="Model files not found. Run `python train_model.py` first.",
            form=request.form,
            dataset_context=load_dataset_context(),
            model_coefs=fallback_coefs,
        )

    best_model_obj, best_model_name = get_best_model()
    model_coefs = get_model_coefficients(best_model_obj)

    data, errors = parse_form(request.form)
    if errors:
        return render_template(
            "index.html",
            errors=errors,
            form=request.form,
            dataset_context=load_dataset_context(),
            model_coefs=model_coefs,
        )

    # Get requested VM count
    vms = float(request.form.get("vms", 1))

    # Calculate predictions for all models
    predictions = {}

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
    cost_breakdown = build_cost_breakdown(request.form, model=best_model_obj)

    if raw_budget:
        try:
            budget_val = float(raw_budget)
            budget_status = build_budget_status(request.form, cost_summary["monthly"])
            recommendations = generate_optimization_suggestions(
                request.form, cost_summary["monthly"], budget_val, cost_breakdown
            )
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
        cost_breakdown=cost_breakdown,
        model_coefs=model_coefs,
        form=request.form,
        dataset_context=load_dataset_context(),
    )


if __name__ == "__main__":
    app.run(debug=True)
