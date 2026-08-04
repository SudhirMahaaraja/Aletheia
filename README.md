# Aletheia

> *The act of revealing what is hidden*

**Aletheia** is a modern, high-performance internal knowledge vault and retrieval-augmented AI assistant. It combines markdown document parsing, vector embeddings, interactive node-graph visualization, GitHub repository indexing, and real-time RAG (Retrieval-Augmented Generation) chat in a single decoupled web platform.

---

## System Architecture

The project is built on a modular, decoupled client-server architecture with an asynchronous pipeline for document ingestion and vector retrieval:

```
┌─────────────────────────────────────────────────────────────┐
│                       React Frontend                        │
│ (Vite, TailwindCSS, Axios Client, Obsidian Local Graph)     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                      REST API / JWT Auth
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                        │
│   (FastAPI, Uvicorn, SentenceTransformers Embedding,        │
│    OpenAI API Integration, BSON, PyPDF/Docx Parsing)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                     MongoDB / Vector Storage
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     MongoDB Database                        │
│  (wiki_embeddings, submissions, github_integrations)        │
└──────────────────────────────┴──────────────────────────────┘
```

### Core Tech Stack
- **Backend Framework:** FastAPI (Python 3.10+) with Uvicorn server
- **Frontend Framework:** React 18 (Vite, TailwindCSS)
- **Database Layer:** MongoDB with Motor (Asynchronous Driver)
- **Vector Embeddings:** `SentenceTransformers` (`all-MiniLM-L6-v2` loaded locally in offline mode)
- **LLM Integration:** OpenAI API / Azure OpenAI (GPT-4o-mini default)
- **Design System:** Ethereal Sage Theme (`#2F4A3B` deep forest green & `#F9F8F3` warm cream)

---

## Key Features

### 1. RAG AI Assistant & Vector Search
- **Multi-Format Document Parsing:** Ingests `.md`, `.txt`, `.pdf`, `.docx`, and `.ipynb` files seamlessly.
- **Jupyter Notebook Support:** Converts markdown and code cells into structured wiki articles.
- **Local Embedding Generation:** Generates 384-dimensional dense vectors locally using HuggingFace `all-MiniLM-L6-v2`.
- **Hybrid Vector Retrieval:** Combines semantic cosine similarity search with exact keyword filters for accurate AI chat context.

### 2. Obsidian-Style Interactive Graph View
- Renders document connections, internal wiki links, and topic relationships using interactive force-directed graph rendering.
- Visualizes vault organization and knowledge clusters in real time.

### 3. Remote GitHub Repository Ingestion
- Allows administrators to index external GitHub repositories into the company knowledge base via GitHub API zipball download.
- Automatically parses codebase structures and indexes source files for AI context querying.

### 4. Role-Based Access Control (RBAC) & Admin Queue
- JWT-based authentication with expiration and role verification (User / Superadmin).
- Submission queue for user uploads with approval/rejection workflows before vault ingestion.

### 5. Ethereal Sage Design System
- **Primary Color:** Deep Forest (`#2F4A3B`)
- **Surface Color:** Warm Cream (`#F9F8F3`)
- **Card Surfaces:** Pure White (`#FFFFFF`) with 1px border & 8px corner radius
- **Controls:** Fully rounded pill tags and 8px input components

---

## Repository Structure

```
.
├── backend/                  # FastAPI Application Server
│   ├── app/                  # Application Core Modules
│   │   ├── controllers/      # API Route Handlers (Auth, Wiki, Chat, GitHub, Admin)
│   │   ├── core/             # Security, JWT, & Configuration
│   │   ├── db/               # MongoDB Motor Database Client
│   │   ├── models/           # Pydantic Schemas & DTO Definitions
│   │   └── views/            # Response Envelopes & Presentation
│   ├── data/                 # Sample Data & Local Database Snapshots
│   ├── main.py               # Backend Entry Point
│   └── requirements.txt      # Python Dependencies
│
├── frontend/                 # React Frontend Application (Vite)
│   ├── src/
│   │   ├── api/              # Axios HTTP Client with Interceptors
│   │   ├── components/       # Reusable UI Layout Components
│   │   ├── context/          # React State Providers (Auth & Chat Context)
│   │   ├── pages/            # View Pages (Wiki, Graph, Chat, Submit, Admin)
│   │   ├── App.jsx           # App Switchboard & Router
│   │   └── index.css         # Ethereal Sage Theme System
│   ├── package.json          # Node.js Dependencies
│   └── vite.config.js        # Vite Configuration
│
├── docs/                     # Documentation & Knowledge Specifications
├── models/                   # Local HuggingFace Embedding Cache
├── .env.example              # Environment Configuration Template
├── .gitignore                # Git Exclusions Policy
└── README.md                 # Project Overview & Setup Guide
```

---

## Environment Configuration

Before running the application, copy the example environment file and configure your local settings:

```bash
cp .env.example .env
```

### Configuration Variables (`.env`)

```ini
# Vault Path (Absolute path to wiki document vault)
VAULT_PATH=D:\Wiki

# MongoDB Connection
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=aletheia_wiki

# OpenAI API Settings
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_ENDPOINT=https://api.openai.com/v1
OPENAI_API_VERSION=2024-08-01-preview
OPENAI_LLM=gpt-4o-mini

# JWT Authentication
JWT_SECRET=your_jwt_secret_key_change_in_production
JWT_EXPIRE_HOURS=24

# File Upload Directory
UPLOAD_DIR=D:\Wiki\uploads

# Server Network Settings
HOST=0.0.0.0
PORT=8000
```

---

## Quick Start Guide

### Prerequisites
- **Python:** 3.10 or higher
- **Node.js:** v18.0 or higher
- **MongoDB:** Running instance on `localhost:27017`

### 1. Setup Backend
```bash
# Navigate to backend directory
cd backend

# Create and activate Python virtual environment
py -3.10 -m venv .venv
# On Windows PowerShell:
.venv\Scripts\activate
# On Linux/macOS:
# source .venv/bin/activate

# Install required packages
pip install -r requirements.txt

# Start FastAPI server
python main.py
```
The backend API service will run on `http://localhost:8000`. API documentation is available at `http://localhost:8000/docs`.

### 2. Setup Frontend
```bash
# Open a new terminal in the frontend directory
cd frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev
```
The frontend interface will run on `http://localhost:5173`.

---

## Pre-Push Checklist

Before pushing this codebase to GitHub, complete the following verification steps:

1. **Check Environment Secrets:**
   Ensure no actual `.env` files or secret keys are committed. Verify with:
   ```bash
   git status
   ```
2. **Verify `.gitignore` Coverage:**
   Confirm that `.venv/`, `node_modules/`, `codebase.zip`, `uploads/`, and `.env` are listed in `.gitignore`.
3. **Clean Build Artifacts:**
   Remove temporary build files and caches:
   ```bash
   # Remove python caches
   find . -type d -name "__pycache__" -exec rm -r {} +
   ```
4. **Test Backend & Frontend Services:**
   - Access OpenAPI documentation at `http://localhost:8000/docs`
   - Access Web UI at `http://localhost:5173`

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
