# Cloud Cost Prediction System

This project predicts cloud service cost from historical cloud resource utilization data. It follows the proposal methodology: preprocessing, feature selection, training multiple regression models, evaluating model performance, comparing results, and using the best model for prediction.

## Dataset Strategy

Do not use a completely random dataset as the main source. For academic submission, use a real/public cloud resource dataset, then adapt it into the final project format. This project now supports dataset adaptation automatically.

The training code maps common CSV column names into these proposal-aligned features:

- `cpu_usage`
- `memory_gb`
- `storage_gb`
- `bandwidth_gb`
- `vm_count`

The prediction target is:

- `cost`

For example, if a dataset has `net_io`, it can be mapped to `bandwidth_gb`; if it has `disk_io`, it can be mapped to `storage_gb`; if it has `vCPU`, it can be used as a VM/count proxy when no better VM-count column exists.

## Features Used

The model trains on canonical final dataset columns:

- `cpu_usage`
- `memory_gb`
- `storage_gb`
- `bandwidth_gb`
- `vm_count`

The prediction target is:

- `cost`

## Models

The training script compares:

- Linear Regression
- Decision Tree Regression
- Random Forest Regression

The best model is selected using the lowest RMSE and saved as `model.pkl`.

## Result Verification

Training also creates `model_metrics.json`, which stores:

- MSE, RMSE, and R2 score for each model
- Best selected model
- Dataset summary
- Dataset feature ranges, providers, regions, and VM types
- Feature importance for the selected model
- A short model selection explanation

The dashboard visualizes model comparison with R2 score bars and explains why the best model was selected. Very high R2 values can occur because this dataset's `cost` values closely follow structured VM pricing fields.

## Cloud Planning Features

The app now includes practical cloud-focused features:

- prediction history logging in `prediction_history.csv`
- monthly budget alert
- VM sizing recommendation
- provider, region, and VM type cost comparison from the dataset
- hourly, daily, and monthly cost estimates
- dataset-aware input limits to keep predictions inside the training range
- dataset context shown on the prediction page and dashboard

The Flask dashboard displays this information at:

```text
http://127.0.0.1:5000/dashboard
```

## Setup

```bash
pip install -r requirements.txt
```

## Train the Model

```bash
python train_model.py
```

Train from another CSV:

```bash
python train_model.py --dataset path/to/your_dataset.csv
```

This creates:

- `model.pkl`
- `model_metrics.json`
- `prepared_training_dataset.csv`

The Flask app uses `prepared_training_dataset.csv` when it exists, so the form limits and dashboard match the dataset used for training.

## Optional Dataset Augmentation

If you need more rows, create an augmented dataset from a real/adapted dataset:

```bash
python augment_dataset.py --input Cloud_Dataset.csv --output Final_Cloud_Dataset.csv --rows 5000
python train_model.py --dataset Final_Cloud_Dataset.csv
```

This does not create a purely random dataset. It samples existing real records and applies small controlled variation. In the report, describe it as an adapted and augmented dataset derived from a public cloud workload dataset.

## Run the App

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## App Pages

- `/` - prediction form, cost estimates, and optimization suggestions
- `/dashboard` - model comparison, dataset summary, feature importance, and prediction history

## Docker Deployment

Build and run locally with Docker:

```bash
docker compose up --build
```

Open:

```text
http://127.0.0.1:5000
```

## Cloud VM Deployment Process

1. Create a small cloud VM on AWS, Azure, or Google Cloud.
2. Install Python, Git, and Docker.
3. Copy or clone this project onto the VM.
4. Run `python train_model.py` to generate `model.pkl` and `model_metrics.json`.
5. Run `docker compose up --build -d`.
6. Open port `5000` in the VM firewall/security group.
7. Access the app using `http://VM_PUBLIC_IP:5000`.

For production, place the app behind a load balancer or reverse proxy and use monitoring/logging to track prediction traffic.
