# Cloud Cost Prediction System ☁️💰

An interactive, high-fidelity, and decoupled machine learning application designed to estimate cloud infrastructure costs from historical resource utilization metrics. Built with **Flask**, **Scikit-Learn**, and **Bootstrap (Glassmorphism UI)**, the system helps developers and enterprises size their cloud instances, compare ML model metrics, get dynamic budget-aware recommendations, and keep track of predictions.

---

## 🏗️ System Architecture (Decoupled Microservices)

The application features a decoupled, production-grade microservices architecture designed to be stateless and scalable.

```mermaid
graph TD
    Client([Web Browser / User]) -->|HTTP Port 5000| WebApp[Web Frontend App <br/> app.py]
    WebApp -->|SQL Query / Connection Pool| DB[(Database <br/> PostgreSQL / SQLite)]
    WebApp -->|REST POST /predict Port 5001| ModelServer[Model Serving Microservice <br/> model_server.py]
    ModelServer -->|Loads weights| Models[ML Models <br/> model.pkl / models.pkl]
```

1. **Web Frontend Tier (`app.py`):** Serves the UI, handles user configuration, executes optimization recommendations, manages SQL operations via connection pooling, and acts as the gateway to the ML model.
2. **Model Serving Tier (`model_server.py`):** A lightweight inference microservice that loads trained ML model weights and exposes a `/predict` REST endpoint for real-time predictions.
3. **Database Tier (`predictions.db` / PostgreSQL):** Logs all predictions. Uses a thread-safe connection pool with **Render PostgreSQL** in production and falls back to local **SQLite** when running locally.

---

## 📊 Dataset & Feature Engineering

The models are trained on real-world cloud workload data. The pipeline maps raw input data into five canonical features:
- `cpu_usage` (vCPUs/Core Hours)
- `memory_gb` (RAM allocated)
- `storage_gb` (Storage capacity)
- `bandwidth_gb` (Network egress transfer)
- `vm_count` (Number of virtual machines in cluster)

The target variable is **`cost`** (monetary hourly expense).

- **`Cloud_Dataset.csv`**: Baseline dataset containing real cloud workload records.
- **`Final_Cloud_Dataset.csv`**: An augmented dataset with 5,000+ records generated via a noise-controlled scaling algorithm to improve regression generalization.

---

## 🤖 Models & Evaluation

The training script automatically trains, evaluates, and compares three core machine learning models:
1. **Linear Regression:** Baseline parametric regression mapping resource coefficients.
2. **Decision Tree Regression:** Non-linear rule-based regression.
3. **Random Forest Regression:** High-accuracy ensemble bagging regressor.

Models are evaluated using 5-fold cross-validation and test-split metrics (MSE, RMSE, $R^2$). The model with the lowest **RMSE** is automatically selected as the active model for inference.

---

## 🚀 Key Features

* **Glassmorphism UI:** Built with Outfit typography, custom sliders, responsive layouts, and interactive dashboards.
* **Budget-Aware Advisor:** Generates dynamic, cost-impact-based optimization suggestions (reductions or family swaps) if predictions exceed your monthly budget.
* **Side-by-Side Model Comparison:** View predictions across all three models concurrently.
* **Detailed Cost Breakdown:** A breakdown highlighting the percentage cost contribution of each hardware resource.
* **Persistent History Log:** Searchable and scrollable list of all previous predictions stored inside the relational database.

---

## 🛠️ Local Setup & Running

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Train Models & Preprocess Dataset
```bash
python train_model.py
```
This generates:
- `model.pkl` (Best model weights)
- `models.pkl` (Dictionary containing all trained models)
- `model_metrics.json` (Calculated metrics, features importance, and metadata)
- `prepared_training_dataset.csv` (Preprocessed dataset used to dynamically bound frontend sliders)

*(Optional: Augment dataset rows)*:
```bash
python augment_dataset.py --rows 5000
```

### 3. Run the Microservices Locally

**Option A: Standard Flask Development (Monolith Fallback)**
If run directly, the web tier automatically loads the local models as a fallback:
```bash
python app.py
```
Visit: [http://127.0.0.1:5000](http://127.0.0.1:5000)

**Option B: Separate Microservice Processes**
Start the inference server (Port 5001):
```bash
$env:PORT="5001"
python model_server.py
```
Start the web app (Port 5000, pointing to the server):
```bash
$env:MODEL_SERVER_URL="http://127.0.0.1:5001"
python app.py
```

---

## 🐳 Docker Deployment (Recommended)

Run the entire multi-container environment (Frontend + Inference Server) with a single command:
```bash
docker compose up --build
```
Access the application dashboard at [http://127.0.0.1:5000](http://127.0.0.1:5000).

---

## ☁️ Production Deployment on Render

This project contains a `render.yaml` blueprint for fully automated Infrastructure as Code (IaC) deployment:
1. Link your repository to **Render**.
2. Render will automatically provision:
   - A **PostgreSQL database** instance.
   - A **Model Inference Service** (running `model_server.py`).
   - A **Frontend Web Service** (running `app.py`, connected to the database and inference server).
3. The environment variables (`DATABASE_URL`, `MODEL_SERVER_URL`) will automatically wire the services together.
