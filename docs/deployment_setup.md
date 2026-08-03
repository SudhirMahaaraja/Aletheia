# Deployment and Setup Guide

This document provides step-by-step instructions for configuring and running the platform locally or in a production environment.

---

## 📋 Prerequisites

Before running the application, make sure the following dependencies are installed on the system:

1. **Python 3.10+**: Core backend runtime (verify with `python --version`).
2. **Node.js 18+**: Frontend Vite build system (verify with `node --version`).
3. **MongoDB**: Local community server running on port `27017` (default).

---

## 🛠️ Environment Configuration

Create a `.env` file in the root `backend/` directory. Use the template below to configure system variables:

```ini
# Absolute directory path where source documents and Markdown wiki files are stored
VAULT_PATH=d:\Wiki\backend\data\vault

# MongoDB configuration
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=knowledge_wiki

# OpenAI API config (supports Direct OpenAI or Azure OpenAI Endpoint)
OPENAI_API_KEY=your_openai_api_key
OPENAI_ENDPOINT=https://your-azure-or-openai-endpoint
OPENAI_API_VERSION=2024-08-01-preview
OPENAI_CHAT_MODEL=gpt-4o

# JWT authentication secret keys
JWT_SECRET=supersecretjwtkey1234567890
JWT_EXPIRE_HOURS=24

# Temporary folder where uploaded files are held during chunk parsing
UPLOAD_DIR=d:\Wiki\backend\uploads

# REST API network binding configs
HOST=0.0.0.0
PORT=8000
```

---

## 🚀 Step-by-Step Installation

### Step 1: Backend Environment Setup
Navigate to the root directory and create the Python virtual environment:
```bash
# Verify you are in the workspace root (d:\Wiki)
# Create the virtual environment
py -3.10 -m venv .venv

# Activate the virtual environment
.venv\Scripts\activate

# Install all backend pip dependencies
pip install -r requirements.txt
```

### Step 2: Frontend Dependency Setup
Install the Node.js packages required to run and build the Vite interface:
```bash
# Navigate to the frontend directory
cd frontend

# Install npm packages
npm install

# Return to root directory
cd ..
```

---

## ⚡ Running the Application

To run both the backend FastAPI application and the Vite frontend dev server in parallel, execute the unified startup script:

```bash
# Make sure the virtual environment is activated (.venv\Scripts\activate)
# Run the entry-point script from root
python backend/main.py
```

### Server Endpoint Details:
* **Backend API**: `http://localhost:8000` (exposes Swagger API documentation at `http://localhost:8000/docs`).
* **Frontend UI**: `http://localhost:5173` (Vite development hot-reload host).

---

## ⚙️ Windows Environment Details

* **Paths**: Ensure all paths configured in `.env` (like `VAULT_PATH` and `UPLOAD_DIR`) use absolute absolute paths and contain forward slashes `/` or escaped backward slashes `\\` to prevent escape character parsing errors in Python.
* **Graphify**: The ingestion pipeline dynamically searches for `graphify.exe` inside `.venv/Scripts/` when running on Windows. Ensure this binary is accessible in the active python environment.
