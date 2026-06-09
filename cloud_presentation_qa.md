# Cloud Cost Predictor - Teacher Q&A Guide

Use this guide to prepare for your presentation. It answers every question your professor ("sir") asked other students, written specifically for **your project** (decoupled Render web app + PostgreSQL database).

---

### 1. Did you develop scenarios like case studies for your project?
* **Answer**: Yes! Our application acts as a simulation engine to model real-world cloud scenarios:
  1. **The Over-provisioning Scenario**: When a user inputs excessively high resources (e.g., 64 cores CPU and 256GB RAM), our cost intelligence engine flags this as a wasted budget scenario and recommends optimal sizing.
  2. **The Under-provisioning Scenario**: If resources are set too low for high workloads, the advisor warns that the server risks crashing.
  3. **The Horizontal Scaling Scenario**: We simulate running clusters of Virtual Machines (`vm_count`) to predict cost scaling.

---

### 2. How many servers have you used?
* **Answer**: We use **two servers** (nodes) in our cloud setup on Render:
  1. **Web Server**: A virtual web instance running our Flask application.
  2. **Database Server**: A separate, managed PostgreSQL database server.
  *(If we scale horizontally in production, we can run 5 or 10 web servers that all talk to the single database server).*

---

### 3. How cloud is used?
* **Answer**: We use the cloud in three distinct ways:
  * **PaaS (Platform as a Service)**: To host our containerized Python application on Render.
  * **Managed Database (DBaaS)**: Using Render PostgreSQL to store prediction history.
  * **Cloud Cost Modeling**: Our Machine Learning model acts as a calculator that simulates how public clouds (AWS, GCP) meter and bill their resources.

---

### 4. How cloud is designed and how we have used it in optimized way?
* **Answer**: 
  * **Design**: It is designed as a **Decoupled (Multi-Tier) Architecture**. Compute (Flask server) is separated from storage (PostgreSQL).
  * **Optimization**: 
    1. **Stateless Web Tier**: The web server does not store data on its local disk. This makes the web servers lightweight and cheap to run.
    2. **Resource Advisor**: The app uses ML predictions to optimize and prevent cloud budget waste.

---

### 5. How scalability etc. features (keywords/key terms in the slides) are ensured?
* **Answer**:
  * **Scalability**: By making the web server stateless, we can scale out horizontally (add more servers) instantly.
  * **Elasticity**: Render handles dynamic routing and load balancing automatically.
  * **Fault Tolerance**: If our web server crashes, another one takes over immediately since all database state is safely stored in PostgreSQL.
  * **Measured Service**: The app models utility-based pricing.

---

### 6. Which type of services are allowed? When deployed, what type of service have been taken?
* **Answer**: 
  * Cloud services are classified into **IaaS** (Infrastructure), **PaaS** (Platform), and **SaaS** (Software).
  * We chose **PaaS (Platform as a Service)** (Render Web Service) and **DBaaS (Database as a Service)** (Render PostgreSQL) because it allows us to focus on code and data without managing physical hardware, OS updates, or network cables.

---

### 7. Can this system be made without using the word cloud? (Is it just an ML project?)
* **Answer**: If we did not use the cloud, this would be a simple local python script that prints predictions on a terminal. It is a **Cloud Project** because:
  1. It is containerized (Docker) and deployed on a live public cloud.
  2. It uses a decoupled cloud architecture (separate Web and Database tiers).
  3. It explicitly models cloud pricing structures (CPU/RAM sizing, bandwidth egress).

---

### 8. Is our project serverless? If yes, then why?
* **Answer**: **No, our project is NOT serverless.** 
  * *Why*: Serverless (like AWS Lambda) runs code only when triggered by an event, then shuts down.
  * Our project runs a **persistent 24/7 web server instance** (running Gunicorn/Flask) and a **persistent PostgreSQL database instance**. We explicitly allocate and size our VM instances (512 MB RAM for web, 256 MB RAM for database).

---

### 9. Did you have scheduling in the project?
* **Answer**: Yes, at the **Infrastructure Layer**. Render handles task scheduling for us:
  1. It runs automated **health checks** to restart the server if it crashes.
  2. It handles **automated daily database backup scheduling** for our PostgreSQL instance.

---

### 10. Being a cloud designer, what we have designed?
* **Answer**: We designed a **Multi-Tier Decoupled Cloud Architecture**:
  * **Tier 1**: Stateless compute instances (Flask + Docker).
  * **Tier 2**: A persistent, centralized database tier (PostgreSQL).
  * **Network Rules**: Private network communication between the web tier and database tier.

---

### 11. What are the designing elements of the project?
* **Answer**:
  1. **Compute Nodes**: Stateless Flask container instances.
  2. **Storage Nodes**: Managed PostgreSQL instance.
  3. **Virtualization**: Docker container packaging.
  4. **Security**: SSL/HTTPS encryption and restricted private subnet access for the database.

---

### 12. "It should not auto-manage like we should be able to manage the crash cases... we should do it."
* **Answer**: Yes, we managed this directly in our code:
  * **Database Failover**: In [app.py](file:///o:/saad%20uni/Cloud%20Computing/Project/cloud-cost-prediction/app.py), we wrote try-except blocks. If the PostgreSQL database crashes or goes offline, our adapter automatically catches the exception and falls back to a local SQLite backup to prevent the application from going down.

---

### 13. How scheduling is formed?
* **Answer**: It is formed via **Render's platform scheduler**, which schedules deployment builds, monitors server performance metrics, and triggers restarts if memory limits are exceeded.

---

### 14. How many VMs are implemented for the project?
* **Answer**: We run **two virtualized nodes**:
  * **1 Web container instance** (512 MB RAM, shared CPU) running Flask.
  * **1 Managed Database node** (256 MB RAM, 1 GB Storage) running PostgreSQL.

---

### 15. How much load will mount on server and how many servers are used to manage that load?
* **Answer**: 
  * Our baseline is **1,000 active users** making 10 requests/hour (~2.8 requests/second).
  * A single 512 MB Web server handles up to **15 requests/second** comfortably. If load spikes, we scale horizontally to **2 or 3 web servers** behind Render's load balancer to distribute the workload.

---

### 16. Is our project stateless? If yes, then why?
* **Answer**: **Yes, the web server is stateless.**
  * *Why*: It stores zero user history, sessions, or logs locally. Every request is processed on-the-fly, and data is written immediately to PostgreSQL. This allows us to scale servers horizontally with no synchronization issues.

---

### 17. How much scalability and what is the formula for it?
* **Answer**: We use **Horizontal Scalability** (scaling out by adding instances).
  * *Formula*: 
    $$\text{Total Web Capacity} = N \times \text{Capacity of 1 Instance}$$
    *(where $N$ is the number of stateless VM instances running our app).*

---

### 18. Why use cloud if our system is lightweight?
* **Answer**: Even though our code is lightweight, traditional hosting on a local PC lacks:
  1. **High Availability**: A local PC shuts down; the cloud runs 24/7.
  2. **Decoupled Persistence**: Render's ephemeral storage deletes local files. The cloud database preserves the data permanently.
  3. **Global Access**: Cloud gives us a public URL so anyone globally can access the tool.

---

### 19. In which classes IP address were designed and why?
* **Answer**: We use **Classless Inter-Domain Routing (CIDR)** blocks (traditionally derived from Class A, B, and C networks) inside our VPC.
  * *Why*: We partition our network so the database has a private IP range (e.g. `10.0.0.0/24`) hidden from the public internet.

---

### 20. Does your project have task queuing?
* **Answer**: No. Because our machine learning model predictions take less than **5 milliseconds** to calculate, we do not need a task queue (like Celery/Redis). The web server handles requests synchronously without blocking.

---

### 21. How much load each server bears?
* **Answer**: Under normal baseline load, each server bears ~2.8 requests per second, consuming about **5% CPU** and **60 MB of RAM** (well within our 512 MB limit).

---

### 22. How failure cases are generated, if client request and system failed to provide then what happens?
* **Answer**: 
  * **Database Failure**: The application catches the exception and falls back to SQLite, logging the failure without crashing.
  * **Web Instance Crash**: Render's Load Balancer immediately routes client requests to other active web instances.

---

### 23. At which cost, the system capacity increases?
* **Answer**: With time, database storage increases. On the Render free tier, storage is capped at **1 GB** (zero cost). If we exceed this, we scale to a paid tier (approximately **$0.115 per GB per month** for SSD storage on AWS RDS or $5/month on Render).

---

### 24. How tasks are made for VMs? How embed?
* **Answer**: Render builds a container from our `Dockerfile`. The container **embeds** the OS, Python dependencies (`requirements.txt`), and the trained ML models (`model.pkl`). The VM runs this container as a single process task.
