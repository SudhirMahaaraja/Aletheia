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
- JWT authentication with refresh token revocation flow.
- Structured audit logs for user logins, document uploads, and administrative actions.

---

## Repository Structure

```
.
├── backend/                              # Core Application Engine
│   ├── app/
│   │   └── controllers/                  # Service Controllers & Engines
│   │       ├── ingestion/                # Ingestion Pipeline & Parsers
│   │       │   ├── parsers/              # AST & Document Parsers (Python, JS, SQL, Doc)
│   │       │   ├── chunker.py            # Code & Text Chunk Router
│   │       │   ├── design_extractor.py   # UI/Design System Extractor
│   │       │   ├── embedder.py           # Local & Remote Vector Embedder
│   │       │   ├── graph_builder.py      # Graphifyy Knowledge Graph Builder
│   │       │   └── pipeline.py           # Master Async Ingestion Pipeline
│   │       ├── rag/                      # RAG Engines
│   │       │   ├── brainstorm.py         # Architectural Brainstorm Engine
│   │       │   ├── repo_chat.py          # Codebase RAG Assistant
│   │       │   ├── retriever.py          # Dual Vector & Hybrid Retriever
│   │       │   └── vault_chat.py         # Vault Knowledge Assistant
│   │       ├── auth_controller.py        # Authentication & Role Management
│   │       ├── github_controller.py      # GitHub Integration Service
│   │       ├── graph_store.py           # Graph Query & Traversal Service
│   │       ├── vault_manager.py          # Local Vault File Operations
│   │       └── vector_store.py           # Vector Index & Search Store
│   ├── core/                             # Infrastructure & Core Configuration
│   │   ├── config.py                     # Pydantic Settings & Env Config
│   │   ├── dependencies.py               # FastAPI Dependencies & DB Injections
│   │   ├── embeddings.py                 # SentenceTransformers Models Loader
│   │   ├── logging_config.py             # Structured App Logger
│   │   └── security.py                   # JWT Utilities & Password Hashing
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
```

---

## License

Distributed under the MIT License. See `LICENSE` for more information.

