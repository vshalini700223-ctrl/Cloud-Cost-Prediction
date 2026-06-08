# Cloud Cost Predictor - Simplified Cloud Architecture & Class Slides Report

This document explains how our **Cloud Cost Prediction System** works in the cloud, mapped directly to what you learned in your Cloud Computing classes (Weeks 1 to 5). It uses simple terms so you can easily understand and explain it to your teacher.

---

## 🗺️ Part 1: Course Keywords Explained Simply

Here is how the main keywords from your slides are actually used in our project:

| Keyword from Slides | What it Means in Plain English | How We Implemented It |
| :--- | :--- | :--- |
| **Measured Service / Utility Computing** | Paying for cloud resources like a utility bill (just like paying for water or electricity based on how much you consume). | Our application takes CPU, RAM, and Storage numbers and calculates (predicts) the exact utility cost that cloud providers would bill you. |
| **Dynamic Resizing / Elasticity** | Changing the size of your server (making CPU, RAM, or storage bigger or smaller) whenever your traffic changes. | Our slider controls let users change CPU/RAM dynamically. The application instantly predicts how this resizing changes the monthly price. |
| **Virtual Clusters** | Running multiple Virtual Machines (VMs) together as a team to handle heavy workloads. | We added a **VM Count** slider in the app. The app automatically calculates the total cost of running a cluster of several VMs. |
| **Over-provisioning** | Wasting money by buying a server that is way too big for your actual needs. | Our **Optimization Advisor** checks your inputs. If your server is too big, it warns you: *"You are over-provisioned (wasting money). Swap to a smaller size to save money!"* |
| **Under-provisioning** | Saving money but renting a server that is too small, causing the site to crash under heavy load. | If your inputs are dangerously low (e.g., too little RAM for heavy workloads), the advisor warns you that your server might crash. |
| **Decoupled Architecture** | Separating the web application (the brain) from the database (the memory) so they run on completely separate servers. | We moved our database from a local file (SQLite) to a separate cloud database (PostgreSQL on Render). Now, if the web server crashes, no data is lost because the database is separate! |

---

## 🏗️ Part 2: Cloud Architecture Design ("Hissab" vs. "Behisaab")

In cloud computing, nothing is truly infinite ("Behisaab"). Every system has limits ("Hissab") that we must plan for. Here is our starting plan and how we grow in the future.

### 1. Where the Story Begins (Our Baseline)
Our system is designed to support **1,000 active users** making up to 10 predictions per hour.
* **The Server**: 1 Virtual Machine (VM) on the cloud (like AWS `t3.micro`) with **2 CPUs** and **1 GB RAM**.
* **The Storage**: **20 GB SSD Disk** (used to store the operating system and run the app).
* **The Network**: Hard limit of **10 GB / month** of outgoing data (downloads/visits).

### 2. The Hard Physical Limits ("Hissab")
Even in the cloud, a cheap VM has strict physical boundaries:
* **RAM Limit (1 GB)**: If our web server uses more than 1 GB of memory, the operating system will immediately crash the app to save itself (this is called an **OOM crash** or Out-Of-Memory crash).
* **CPU Credits**: Cheap cloud VMs are "burstable". They work fast for short periods, but if they are under heavy load for too long, the cloud provider slows the CPU down to 10% speed.

---

## 🛜 Part 3: How the Network Works (The Protocol Stack)

We set up our network rules based on the standard **TCP/IP stack** (the communication layers):

```mermaid
graph TD
    User([Clients / Web Browsers]) -->|TCP/IP Port 80/443| LB[Elastic Load Balancer]
    LB -->|Subnet Routing| ASG[Auto-Scaling Group]
    subgraph VPC [Virtual Private Cloud VPC]
        subgraph PublicSubnet [Public Subnet - Web Tier]
            ASG --> VM1[Web VM Instance 1]
            ASG --> VM2[Web VM Instance 2]
        end
        subgraph PrivateSubnet [Private Subnet - Database Tier]
            VM1 --> DB[(Managed PostgreSQL Database on Render)]
            VM2 --> DB
        end
    end
```

1. **Virtual Private Cloud (VPC)**: This is our private sandbox network in the cloud. Nobody can access it unless we allow them.
2. **Public Subnet (Web Server)**: The web server runs here. We opened **Port 80/443 (HTTP/HTTPS)** so users on the internet can visit the website.
3. **Private Subnet (Database)**: Our PostgreSQL database runs here. It is completely locked and invisible to the public internet. Only our web servers are allowed to talk to it.
4. **Reliable Communication (TCP)**: Client requests and predictions are sent over **TCP** to make sure no data gets lost along the way.

---

## 📈 Part 4: How We Scale Up in the Future

If our user base grows from **1,000 to 100,000+ users**, we scale up using three steps:

1. **Load Balancer**: We put a Load Balancer at the front door. When a user visits, it redirects them to the server that is least busy.
2. **Horizontal Scaling**: Instead of one server, we run a cluster of 5 or 10 servers. If traffic spikes, Render/AWS automatically starts up new servers to help.
3. **Centralized Database**: Because we separated our database (PostgreSQL), all web servers talk to the same database. This keeps all prediction history perfectly synchronized for all users, no matter which server they are connected to!
