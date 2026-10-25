import os
import json
from pathlib import Path
from flask import Flask, request, jsonify
import joblib
import pandas as pd

app = Flask(__name__)

MODEL_PATH = Path("model.pkl")
METRICS_PATH = Path("model_metrics.json")
MODELS_DICT_PATH = Path("models.pkl")

# Load models at startup
models = {}
if MODELS_DICT_PATH.exists():
    try:
        loaded = joblib.load(MODELS_DICT_PATH)
        if isinstance(loaded, dict):
            models = loaded
    except Exception as e:
        print(f"Error loading models.pkl: {e}")

if not models and MODEL_PATH.exists():
    try:
        single_model = joblib.load(MODEL_PATH)
        models = {"Best Model": single_model}
    except Exception as e:
        print(f"Error loading model.pkl: {e}")

# Load metrics
metrics = None
if METRICS_PATH.exists():
    try:
        with open(METRICS_PATH, "r", encoding="utf-8") as file:
            metrics = json.load(file)
    except Exception as e:
        print(f"Error loading model_metrics.json: {e}")


def get_model_coefficients(model):
    if model is not None and hasattr(model, "coef_"):
        coefs = list(model.coef_)
        return {
            "cpu":       round(abs(float(coefs[0])), 8),
            "memory":    round(abs(float(coefs[1])), 8),
            "storage":   round(abs(float(coefs[2])), 8),
            "bandwidth": round(abs(float(coefs[3])), 8),
        }
    return {"cpu": 0.0001, "memory": 0.004, "storage": 0.00005, "bandwidth": 0.0001}


def get_best_model_name():
    if metrics and "best_model" in metrics:
        best_name = metrics["best_model"]
        if best_name in models:
            return best_name
    if models:
        return list(models.keys())[0]
    return None


@app.route("/metadata", methods=["GET"])
def metadata():
    best_name = get_best_model_name()
    best_model_obj = models.get(best_name) if best_name else None
    coefs = get_model_coefficients(best_model_obj)
    
    return jsonify({
        "best_model": best_name,
        "coefficients": coefs,
        "models": list(models.keys())
    })


@app.route("/predict", methods=["POST"])
def predict():
    try:
        req_data = request.get_json()
        if not req_data:
            return jsonify({"error": "No input data provided"}), 400
        
        # Load input features into DataFrame
        df = pd.DataFrame(req_data)
        
        # Make predictions for each model loaded
        predictions = {}
        for name, m in models.items():
            df_unit = df.copy()
            if "vm_count" in df_unit.columns:
                df_unit["vm_count"] = 1.0
            
            pred = float(m.predict(df_unit)[0])
            predictions[name] = pred
            
        return jsonify({
            "predictions": predictions
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
