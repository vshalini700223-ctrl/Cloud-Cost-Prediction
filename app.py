import sqlite3
import json
import os
import requests
import threading
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
DB_PATH = Path("predictions.db")
DATASET_CONTEXT = None

# Global PostgreSQL connection pool
pg_pool = None
DATABASE_URL = os.environ.get("DATABASE_URL")
MODEL_SERVER_URL = os.environ.get("MODEL_SERVER_URL")

def init_pg_pool():
    global pg_pool
    if DATABASE_URL and pg_pool is None:
        try:
            from psycopg2 import pool
            # Min 1, Max 10 active connections in pool (thread-safe ThreadedConnectionPool)
            pg_pool = pool.ThreadedConnectionPool(1, 10, dsn=DATABASE_URL)
            print("PostgreSQL connection pool initialized successfully.")
        except Exception as e:
            print("Failed to initialize PostgreSQL connection pool.")

init_pg_pool()


def get_db_connection():
    global pg_pool
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if pg_pool is None:
            init_pg_pool()
        if pg_pool:
            return pg_pool.getconn(), True
    # Fallback to local SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn, False


def execute_query(query, params=(), fetch=False, fetch_all=True):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from psycopg2.extras import RealDictCursor
        query = query.replace("?", "%s")
        conn = None
        try:
            conn, is_pg = get_db_connection()
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    if fetch:
                        if fetch_all:
                            return [dict(row) for row in cursor.fetchall()]
                        else:
                            row = cursor.fetchone()
                            return dict(row) if row else None
            return None
        except Exception as e:
            print("Database query execution error occurred (credentials hidden).")
            raise e
        finally:
            if conn and pg_pool:
                pg_pool.putconn(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if fetch:
                    if fetch_all:
                        return [dict(row) for row in cursor.fetchall()]
                    else:
                        row = cursor.fetchone()
                        return dict(row) if row else None
            return None
        finally:
            conn.close()


def init_db():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if pg_pool is None:
            init_pg_pool()
        if pg_pool:
            conn = None
            try:
                conn = pg_pool.getconn()
                with conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS predictions (
                                id SERIAL PRIMARY KEY,
                                timestamp VARCHAR(50),
                                cpu_usage REAL,
                                memory_gb REAL,
                                storage_gb REAL,
                                bandwidth_gb REAL,
                                vm_count REAL,
                                monthly_budget REAL,
                                hourly_cost REAL,
                                daily_cost REAL,
                                monthly_cost REAL,
                                budget_status VARCHAR(100),
                                recommendations TEXT
                            )
                        """)
            except Exception as e:
                print("Failed to initialize database table in PostgreSQL.")
            finally:
                if conn and pg_pool:
                    pg_pool.putconn(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        cpu_usage REAL,
                        memory_gb REAL,
                        storage_gb REAL,
                        bandwidth_gb REAL,
                        vm_count REAL,
                        monthly_budget REAL,
                        hourly_cost REAL,
                        daily_cost REAL,
                        monthly_cost REAL,
                        budget_status TEXT,
                        recommendations TEXT
                    )
                """)
        finally:
            conn.close()


init_db()


def get_active_dataset_path():
    return PREPARED_DATASET_PATH if PREPARED_DATASET_PATH.exists() else DATASET_PATH


MODELS_DICT_PATH = Path("models.pkl")

# Lazy loading local models to save memory in cloud production
_local_models = None

def get_local_models():
    global _local_models
    if _local_models is None:
        _local_models = load_models()
    return _local_models


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


def load_metrics():
    if not METRICS_PATH.exists():
        return None
    with open(METRICS_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def get_metadata():
    if MODEL_SERVER_URL:
        try:
            response = requests.get(f"{MODEL_SERVER_URL}/metadata", timeout=2.0)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Failed to fetch model metadata from remote server: {e}")

    # Local fallback
    best_model_name = None
    metrics = load_metrics()
    if metrics and "best_model" in metrics:
        best_model_name = metrics["best_model"]

    local_models = get_local_models()
    if not best_model_name and local_models:
        best_model_name = list(local_models.keys())[0]

    best_model_obj = local_models.get(best_model_name) if best_model_name else None
    coefs = get_model_coefficients(best_model_obj)

    return {
        "best_model": best_model_name,
        "coefficients": coefs,
        "models": list(local_models.keys())
    }


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
    database_url = os.environ.get("DATABASE_URL")
    if not database_url and not DB_PATH.exists():
        return []
    try:
        rows = execute_query("""
            SELECT timestamp, cpu_usage, memory_gb, storage_gb, bandwidth_gb, vm_count,
                   monthly_budget, hourly_cost, daily_cost, monthly_cost, budget_status, recommendations
            FROM predictions
            ORDER BY id DESC
            LIMIT ?
        """, (limit,), fetch=True)
        return rows if rows else []
    except Exception as e:
        print(f"Error loading history: {e}")
        return []


def save_prediction(form, cost_summary, recommendations, budget_status):
    try:
        cpu = float(form.get("cpu", 0))
        memory = float(form.get("memory", 0))
        storage = float(form.get("storage", 0))
        bandwidth = float(form.get("bandwidth", 0))
        vms = float(form.get("vms", 1))
        budget = float(form.get("budget", 0)) if form.get("budget", "").strip() else None

        rec_text = " | ".join(
            r["text"] if isinstance(r, dict) else r
            for r in recommendations
        )

        execute_query("""
            INSERT INTO predictions (
                timestamp, cpu_usage, memory_gb, storage_gb, bandwidth_gb, vm_count,
                monthly_budget, hourly_cost, daily_cost, monthly_cost, budget_status, recommendations
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            cpu, memory, storage, bandwidth, vms,
            budget,
            cost_summary["hourly"],
            cost_summary["daily"],
            cost_summary["monthly"],
            budget_status["status"] if budget_status else "",
            rec_text
        ))
    except Exception as e:
        print(f"Database error: {e}")


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


def build_cost_breakdown(form, model=None, coefs=None):
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

    if coefs is None:
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
                f"✅ Your resource configuration is already optimized and fits within "
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
                f"(e.g., compute-optimized or burstable instances) "
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
    meta = get_metadata()
    return render_template(
        "index.html",
        dataset_context=load_dataset_context(),
        model_coefs=meta["coefficients"],
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
    meta = get_metadata()
    best_model_name = meta["best_model"]
    model_coefs = meta["coefficients"]
    model_names = meta["models"]

    if not model_names:
        fallback_coefs = {"cpu": 0.0001, "memory": 0.004, "storage": 0.00005, "bandwidth": 0.0001}
        return render_template(
            "index.html",
            error="Model files not found. Run `python train_model.py` or start the model server.",
            form=request.form,
            dataset_context=load_dataset_context(),
            model_coefs=fallback_coefs,
        )

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

    # Check if we should call the remote Model Server or run locally
    if MODEL_SERVER_URL:
        try:
            features_json = data.to_dict(orient="records")
            response = requests.post(f"{MODEL_SERVER_URL}/predict", json=features_json, timeout=3.0)
            if response.status_code == 200:
                res_predictions = response.json().get("predictions", {})
                for name, pred_unit in res_predictions.items():
                    predictions[name] = round(pred_unit * vms, 4)
        except Exception as e:
            print(f"Remote model prediction failed, trying local fallback: {e}")
            predictions = {}

    # Fallback to local prediction if remote server failed or is not configured
    if not predictions:
        local_models = get_local_models()
        for name, m in local_models.items():
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
    
    # Calculate breakdown
    local_models = get_local_models() if not MODEL_SERVER_URL else {}
    best_model_obj = local_models.get(best_model_name) if best_model_name else None
    cost_breakdown = build_cost_breakdown(request.form, model=best_model_obj, coefs=model_coefs)

    if raw_budget:
        try:
            budget_val = float(raw_budget)
            budget_status = build_budget_status(request.form, cost_summary["monthly"])
            recommendations = generate_optimization_suggestions(
                request.form, cost_summary["monthly"], budget_val, cost_breakdown
            )
        except ValueError:
            pass

    # Async database write to prevent blocking the Flask request thread
    threading.Thread(
        target=save_prediction,
        args=(dict(request.form), cost_summary, recommendations, budget_status),
        daemon=True
    ).start()

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
