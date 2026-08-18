# Aletheia

> *The act of revealing what is hidden*

**Aletheia** is a modern, high-performance internal knowledge vault, code-graph ingestion engine, and retrieval-augmented AI assistant (RAG). It combines multi-language code & document parsing (Python, JavaScript/TypeScript, SQL, PDF, DOCX, Markdown), dense vector embeddings (code & text), Obsidian-compatible Markdown vault generation, knowledge graph construction via Graphifyy, and multi-mode RAG AI engines.

---

## System Architecture

The project is built on a modular, asynchronous backend architecture for multi-source knowledge ingestion, vector retrieval, and RAG chat:

```
┌─────────────────────────────────────────────────────────────┐
│                    Aletheia Core Backend                    │
│      (Python 3.10+, FastAPI Architecture, Motor Async)      │
├──────────────────────────────┬──────────────────────────────┤
│  Ingestion & AST Parsers     │    Multi-Mode RAG Engines   │
│  (Tree-sitter JS, Python,    │   - Vault Chat               │
│   SQL, PDF/Docx, Markdown)   │   - Codebase Repo Chat       │
│  (Graphifyy Graph Builder)   │   - Architectural Brainstorm │
└──────────────┬───────────────┴──────────────┬───────────────┘
               │                              │
     MongoDB & Vector Storage        Embedding Models
               │                   (Jina Code & MiniLM Text)
               ▼                              ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│       MongoDB Database       ││  Knowledge Vault Directory   │
│ (document_chunks,            ││   (data/vault/wiki,          │
│  code_chunks, graph_nodes,   ││    data/vault/raw,           │
│  graph_edges, repositories)  ││    data/vault/graphs)       │
└──────────────────────────────┘└──────────────────────────────┘
```

### Core Tech Stack
- **Backend Framework:** Python 3.10+ with FastAPI / Motor (Asynchronous MongoDB Client)
- **API Router Layer:** Versioned REST API endpoints (`/api/v1/*`) structured into controllers, schemas, and view route handlers
- **Database Engine:** MongoDB managed asynchronously via `Motor` with auto-managed index creation (unique, TTL, and text search indexes)
- **Code & AST Parsing:** Tree-Sitter (`tree-sitter-javascript`), Python AST, `sqlparse`, PyMuPDF (`fitz`), `python-docx`
- **Knowledge Graph Builder:** `graphifyy` AST and concept graph extractor
- **Vector Embeddings:** Dual embedding pipelines:
  - Text Embeddings: `sentence-transformers/all-MiniLM-L6-v2` (384d)
  - Code Embeddings: `jinaai/jina-embeddings-v2-base-code` (768d)
- **LLM Integration:** OpenAI API / Azure OpenAI (GPT-4 / GPT-4o models)
- **Authentication & Security:** JWT tokens (Access & Refresh), PassLib with Bcrypt, role-based authorization (`admin`, `developer`, `pm`), and structured audit logging

---

## Key Features

### 1. Multi-Language Code & Document Ingestion
- **AST Code Parsing:** Extracts functions, classes, dependencies, and calls from Python (`.py`), JavaScript/TypeScript (`.js`, `.jsx`, `.ts`, `.tsx`), and SQL (`.sql`) files.
- **Document & Media Support:** Parses `.md`, `.txt`, `.pdf`, `.docx`, and `.ipynb` files with automated chunking.
- **Design System Extractor:** Automatically analyzes repository design tokens, UI components, and styling conventions (`design_extractor.py`).

### 2. Knowledge Graph Construction & Vault Sync
- Builds node-edge knowledge graphs connecting files, functions, concepts, and documentation via `graphifyy`.
- Generates an Obsidian-compatible Markdown Vault under `data/vault/` with frontmatter metadata and internal wiki links (`[[link]]`).
- Synchronizes graph nodes and edges (`graph_nodes`, `graph_edges`) in MongoDB.

### 3. Multi-Engine RAG Assistant
- **Vault Chat (`vault_chat.py`):** Answers domain knowledge queries based on indexed documentation chunks.
- **Repo Chat (`repo_chat.py`):** Queries source code chunks with file and line range citations.
- **Architectural Brainstorm (`brainstorm.py`):** Generates architectural plans and component recommendations based on indexed codebases and design systems.

### 4. GitHub Remote Ingestion & Automated Mirroring
- Clones and indexes external GitHub repositories.
- Extracts file trees, generates repo overview pages, and mirrors raw source code into local vault structure.

### 5. Role-Based Security & Audit Logging
- JWT authentication with refresh token revocation flow (`auth_controller.py`).
- Structured audit logs for user logins, role modifications, document uploads, and administrative actions (`audit_logs`).

### 6. MongoDB Indexing & Database Management
- Asynchronous MongoDB client (`mongodb.py`) with health ping and index management across collections (`users`, `repositories`, `documents`, `ingestion_jobs`, `chat_sessions`, `chat_messages`, `graph_nodes`, `graph_edges`, `audit_logs`, `code_chunks`, `document_chunks`).
- Configures 90-day TTL indexes on audit logs, unique key constraints on emails/repos, and full-text index on graph nodes.

### 7. Versioned REST API Layer (`/api/v1`)
- **Authentication (`/api/v1/auth`):** Registration, OAuth2 login, token refresh, logout, and current user profile (`/me`).
- **GitHub Connections (`/api/v1/github`):** PAT validation, account activation/deletion, repo listing, branch inspection, and repo selection/deselection.
- **Ingestion Pipeline (`/api/v1/ingest`):** Async repository ingestion, repo-to-vault sync, document upload, project management, and job tracking.
- **RAG Chat & Sessions (`/api/v1/chat`):** Chat session management, message streaming (SSE), and generated document downloads (`.docx`).
- **Semantic Vector Search (`/api/v1/search`):** Multi-collection vector search across code and document embeddings with repository filtering.
- **Knowledge Graph Traversal (`/api/v1/graph`):** Node listing, edge graph traversal, and dynamic concept/wiki page loading.
- **System Administration (`/api/v1/admin`):** User role management, account deletion, system audit logs, and operational statistics.

### 8. FastAPI Lifespan & Background Workers
- **Async Database Connection:** Managed MongoDB connection lifecycle via `Motor`.
- **Background Node Backfilling:** Asynchronously syncs vault files and backfills `Repository` and `File` graph nodes into `graph_nodes` and `graph_edges`.
- **Document Cleanup:** Periodic automated cleanup task for expired generated documents.
- **SPA Frontend Integration:** Embedded static file serving for single-page web frontends with 404 fallback routing and `/health` readiness check.

---

## Repository Structure

```
.
├── backend/                              # Core Application Engine
│   ├── app/
│   │   ├── main.py                       # FastAPI Application Entrypoint & Lifespan Tasks
│   │   ├── controllers/                  # Service Controllers & Business Logic
│   │   │   ├── ingestion/                # Ingestion Pipeline & Parsers
│   │   │   │   ├── parsers/              # AST & Document Parsers (Python, JS, SQL, Doc)
│   │   │   │   ├── chunker.py            # Code & Text Chunk Router
│   │   │   │   ├── design_extractor.py   # UI/Design System Extractor
│   │   │   │   ├── embedder.py           # Local & Remote Vector Embedder
│   │   │   │   ├── graph_builder.py      # Graphifyy Knowledge Graph Builder
│   │   │   │   └── pipeline.py           # Master Async Ingestion Pipeline
│   │   │   ├── rag/                      # RAG Engines
│   │   │   │   ├── brainstorm.py         # Architectural Brainstorm Engine
│   │   │   │   ├── repo_chat.py          # Codebase RAG Assistant
│   │   │   │   ├── retriever.py          # Dual Vector & Hybrid Retriever
│   │   │   │   └── vault_chat.py         # Vault Knowledge Assistant
│   │   │   ├── auth_controller.py        # Authentication & Role Management
│   │   │   ├── github_controller.py      # GitHub Integration Service
│   │   │   ├── graph_store.py           # Graph Query & Traversal Service
│   │   │   ├── vault_manager.py          # Local Vault File Operations
│   │   │   └── vector_store.py           # Vector Index & Search Store
│   │   ├── core/                         # Infrastructure & Core Configuration
│   │   │   ├── config.py                 # Pydantic Settings & Env Config
│   │   │   ├── dependencies.py           # FastAPI Security Dependencies & DB Injections
│   │   │   ├── embeddings.py             # Dual Embedding Loaders & Transformers v5 Patches
│   │   │   ├── logging_config.py         # Structured App Logger
│   │   │   └── security.py               # JWT Utilities & Password Hashing
│   │   ├── db/                           # Database Client & Index Management
│   │   │   └── mongodb.py                # Async Motor Connection Client & Index Creation
│   │   └── views/                        # API View Layer & Pydantic Schemas
│   │       ├── schemas/                  # Request/Response DTO Schemas
│   │       │   ├── admin.py              # User management & Stats DTOs
│   │       │   ├── auth.py               # Login, Register & Token DTOs
│   │       │   ├── chat.py               # Session & Message DTOs
│   │       │   ├── github.py             # PAT & Repository Selection DTOs
│   │       │   ├── graph.py              # Node & Edge Response DTOs
│   │       │   ├── ingest.py             # Ingestion Job & Project DTOs
│   │       │   └── search.py             # Vector Search Result DTOs
│   │       └── v1/                       # Version 1 API Route Handlers
│   │           ├── admin.py              # System Admin & Audit Logs Endpoints
│   │           ├── auth.py               # Authentication & User Info Endpoints
│   │           ├── chat.py               # Multi-Mode RAG Chat & Session Endpoints
│   │           ├── github.py             # Connection & Repository Endpoints
│   │           ├── graph.py              # Knowledge Graph Query & Traversal Endpoints
│   │           ├── ingest.py             # Repository & Document Ingestion Endpoints
│   │           ├── router.py             # Master V1 Router Includer
│   │           └── search.py             # Knowledge Base Vector Search Endpoint
│   └── requirements.txt                  # Backend Python Dependencies
│
├── data/                                 # Knowledge Storage & Vault
│   ├── vault/                            # Obsidian-Compatible Local Vault
│   │   ├── raw/                          # Original File Mirrors
│   │   ├── wiki/                         # Generated Markdown Wiki & Index
│   │   └── graphs/                       # Graphify Output Visualizations
│   ├── graphs/                           # Workspace Graph Snapshots
│   └── raw/                              # Upload Workspace
│
├── docs/                                 # Developer Specifications
│   ├── api_specification.md              # REST Endpoint Specs
│   ├── architecture.md                   # System Architecture Details
│   ├── database_schema.md                # MongoDB Collections Schema
│   ├── deployment_setup.md               # Setup & Environment Guide
│   ├── frontend_guide.md                 # UI Integration Guide
│   ├── index.md                          # Documentation Index
│   └── ingestion_and_graph.md            # Ingestion & Graph Builder Guide
│
├── .env.example                          # Environment Variables Template
├── .gitignore                            # Git Exclusion Rules
└── README.md                             # Project Documentation
```

---

## Environment Configuration

Copy the example environment template to create `.env`:

```bash
cp backend/.env.example backend/.env
```

### Key Configuration Variables (`.env`)

```ini
# MongoDB Connection
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=aletheia_db

# Vault Directory Path
VAULT_PATH=./data/vault

# OpenAI / LLM Settings
OPENAI_API_KEY=your_openai_api_key
OPENAI_CHAT_MODEL=gpt-4o

# Embeddings Configuration
TEXT_EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
CODE_EMBEDDING_MODEL_NAME=jinaai/jina-embeddings-v2-base-code

# JWT Security
JWT_SECRET_KEY=your_jwt_secret_key
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# GitHub PAT (Optional for private repos)
GITHUB_PAT=your_github_personal_access_token
```

---

## Quick Start Guide

### Prerequisites
- **Python:** 3.10+
- **MongoDB:** Running instance at `localhost:27017`

### Setup Backend Engine
```bash
# Navigate to backend folder
cd backend

# Create and activate Python virtual environment
py -3.10 -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run application server
uvicorn app.main:app --reload --port 8000
```

---

## License

Distributed under the MIT License. See `LICENSE` for more information.


