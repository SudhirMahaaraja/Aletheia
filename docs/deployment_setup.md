# Deployment and Setup Guide

This document provides step-by-step instructions for configuring and running the Aletheia platform locally or in a production environment.

---

## 📋 Prerequisites

Before running the application, make sure the following dependencies are installed on the system:

1. **Python 3.10+**: Core backend runtime (verify with `python --version`).
2. **Node.js 18+**: Frontend build system (verify with `node --version`).
3. **MongoDB**: Local community server running on port `27017` (default).

---

## 🛠️ Environment Configuration

Create a `.env` file in the `backend/` directory (or workspace root). Use the template below to configure system variables:

```ini
# Absolute directory path where source documents and Markdown wiki files are stored
VAULT_PATH=d:/Aletheia/data/vault

# MongoDB configuration
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=aletheia_db

# OpenAI API config (supports Direct OpenAI or Azure OpenAI Endpoint)
OPENAI_API_KEY=your_openai_api_key
OPENAI_ENDPOINT=https://api.openai.com/v1
OPENAI_API_VERSION=2024-08-01-preview
OPENAI_CHAT_MODEL=gpt-4o

# JWT authentication secret keys
JWT_SECRET_KEY=supersecretjwtkey1234567890
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# Vector Embedding Models
TEXT_EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
CODE_EMBEDDING_MODEL_NAME=jinaai/jina-embeddings-v2-base-code

# Maximum character guardrail for vector chunking
MAX_EMBEDDING_CHARS=2000

# REST API network binding configs
HOST=0.0.0.0
PORT=8000
```

---

## 🚀 Step-by-Step Installation & Execution

### Step 1: Virtual Environment Setup
Navigate to the `backend/` folder and create/activate the Python virtual environment:
```bash
# Navigate to backend directory
cd backend

# Create the virtual environment
py -3.10 -m venv .venv

# Activate the virtual environment (Windows)
.venv\Scripts\activate

# Install all backend pip dependencies
pip install -r requirements.txt
```

### Step 2: Running the Application Server
With the virtual environment activated, start the FastAPI server via Uvicorn:
```bash
# Run server from the backend directory
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## ⚙️ Server Endpoints and API Documentation

* **Backend API Base**: `http://localhost:8000/api/v1`
* **Swagger API Documentation**: `http://localhost:8000/docs`
* **ReDoc Documentation**: `http://localhost:8000/redoc`
* **Health Check**: `http://localhost:8000/health`

---

## ⚙️ Windows Environment Details

* **Paths**: Ensure all paths configured in `.env` (like `VAULT_PATH`) use absolute paths with forward slashes `/` or escaped backward slashes `\\` to prevent escape character parsing errors in Python.
* **Graphify**: The ingestion pipeline dynamically searches for `graphify.exe` inside `.venv/Scripts/` when running on Windows. Ensure this binary is accessible in the active python environment.

