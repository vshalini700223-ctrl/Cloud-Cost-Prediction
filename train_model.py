import argparse
import json

import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import joblib

from dataset_utils import FEATURE_COLUMNS, TARGET_COLUMN, get_feature_ranges, prepare_dataset

DATASET_PATH = "Final_Cloud_Dataset.csv"
PREPARED_DATASET_PATH = "prepared_training_dataset.csv"
MODEL_PATH = "model.pkl"
METRICS_PATH = "model_metrics.json"


def evaluate(y_true, y_pred):
    mse = mean_squared_error(y_true, y_pred)
    rmse = mse ** 0.5
    r2 = r2_score(y_true, y_pred)
    return {"mse": mse, "rmse": rmse, "r2": r2}


def get_feature_importance(model, X):
    if hasattr(model, "feature_importances_"):
        scores = model.feature_importances_
    elif hasattr(model, "coef_"):
        scores = abs(model.coef_ * X.std(ddof=0).to_numpy())
    else:
        scores = [0] * len(FEATURE_COLUMNS)

    total = sum(float(score) for score in scores) or 1
    importance = [
        {
            "feature": feature,
            "importance": round(float(score) / total, 4),
        }
        for feature, score in zip(FEATURE_COLUMNS, scores)
    ]
    return sorted(importance, key=lambda item: item["importance"], reverse=True)


def get_dataset_summary(df, dataset_info):
    return {
        "rows": int(len(df)),
        "features_used": FEATURE_COLUMNS,
        "target": TARGET_COLUMN,
        "source_file": dataset_info["source_file"],
        "column_mappings": dataset_info["column_mappings"],
        "feature_ranges": get_feature_ranges(df),
        "feature_definitions": dataset_info["feature_definitions"],
        "providers": sorted(df["cloud_provider"].dropna().unique().tolist()) if "cloud_provider" in df else [],
        "regions": sorted(df["region"].dropna().unique().tolist()) if "region" in df else [],
        "vm_types": sorted(df["vm_type"].dropna().unique().tolist()) if "vm_type" in df else [],
        "average_cost": round(float(df[TARGET_COLUMN].mean()), 6),
        "minimum_cost": round(float(df[TARGET_COLUMN].min()), 6),
        "maximum_cost": round(float(df[TARGET_COLUMN].max()), 6),
        "average_utilization": round(float(df["utilization"].mean()), 2) if "utilization" in df else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Train cloud cost prediction models.")
    parser.add_argument("--dataset", default=DATASET_PATH, help="CSV dataset to train from.")
    args = parser.parse_args()

    df, dataset_info = prepare_dataset(args.dataset)
    df.to_csv(PREPARED_DATASET_PATH, index=False)

    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    models = {
        "Linear Regression": LinearRegression(),
        "Decision Tree": DecisionTreeRegressor(random_state=42),
        "Random Forest": RandomForestRegressor(n_estimators=100, random_state=42),
    }

    results = {}
    trained_models = {}

    for name, model in models.items():
        model.fit(X_train, y_train)
        predictions = model.predict(X_test)
        
        # Test evaluation
        eval_metrics = evaluate(y_test, predictions)
        
        # 5-fold cross validation R2 score
        cv_scores = cross_val_score(model, X, y, cv=5, scoring='r2')
        eval_metrics["cv_r2_mean"] = float(cv_scores.mean())
        eval_metrics["cv_r2_std"] = float(cv_scores.std())
        
        results[name] = eval_metrics
        trained_models[name] = model

    for name, metrics in results.items():
        print(
            f"{name}: "
            f"MSE={metrics['mse']:.6f}, "
            f"RMSE={metrics['rmse']:.6f}, "
            f"R2={metrics['r2']:.4f}"
        )

    best_model_name = min(results, key=lambda name: results[name]["rmse"])
    joblib.dump(trained_models[best_model_name], MODEL_PATH)
    joblib.dump(trained_models, "models.pkl")

    metrics_report = {
        "dataset": get_dataset_summary(df, dataset_info),
        "models": {
            name: {metric: round(float(value), 6) for metric, value in metrics.items()}
            for name, metrics in results.items()
        },
        "best_model": best_model_name,
        "selection_note": (
            "The selected model has the lowest RMSE on the held-out test set. "
            "Very high R2 scores are expected here because the dataset cost values "
            "closely follow structured VM pricing fields."
        ),
        "feature_importance": get_feature_importance(trained_models[best_model_name], X),
    }

    with open(METRICS_PATH, "w", encoding="utf-8") as file:
        json.dump(metrics_report, file, indent=4)

    print(f"Best model: {best_model_name}")
    print(f"Model saved to {MODEL_PATH}")
    print(f"Metrics saved to {METRICS_PATH}")
    print(f"Prepared dataset saved to {PREPARED_DATASET_PATH}")


if __name__ == "__main__":
    main()
