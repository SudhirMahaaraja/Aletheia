# System Architecture and Data Flows

This document details the high-level architecture, subsystem data flows, local embedding model integrations, FastAPI background workers, and security mechanisms of the Aletheia platform.

---

## 🏗️ High-Level System Architecture

The platform follows a decoupled client-server architecture designed for clean separation of concerns and maintainability:

```
+-----------------------------------------------------------+
|                       React Frontend                      |
|      (Vite, TailwindCSS, Axios Client, Cytoscape Graph)   |
+-----------------------------------------------------------+
                              │
                      REST API / JWT Auth
                              │
                              ▼
+-----------------------------------------------------------+
|                      FastAPI Backend                      |
|   (FastAPI, Uvicorn, SentenceTransformers Embedding,      |
|    OpenAI API Integration, Motor Async, PyPDF/Docx/ipynb) |
+-----------------------------------------------------------+
                              │
                     MongoDB / Vector Storage
                              │
                              ▼
+-----------------------------------------------------------+
|                     MongoDB Database                      |
|   (Collections: users, documents, document_chunks,        |
|    code_chunks, graph_nodes, graph_edges, repositories,   |
|    ingestion_jobs, github_connections, audit_logs,        |
|    chat_sessions, chat_messages, projects)                |
+-----------------------------------------------------------+
```

1. **Presentation Layer (React Frontend)**: Manages UI rendering, user states, chat interfaces, directory navigation, admin queues, and interactive graph visualizations (Cytoscape.js). It communicates with the backend exclusively via versioned HTTP REST endpoints (`/api/v1/*`).
2. **Application Layer (FastAPI Backend)**: Organizes logic into controllers, models, schemas, and views. Handles route dispatching, security dependencies, file parser dispatchers, AST code analysis, LLM completions, and vector store operations.
3. **Database Layer (MongoDB)**: Persists all state including user accounts, parsed document metadata, code/text chunks, vectors (saved directly on the chunks for similarity search), knowledge graph nodes/edges, audit logs, and project metadata.

---

## 🔄 Background Lifespan Workers & Queue Tasks

FastAPI lifespan hooks and async background tasks execute essential platform maintenance:

1. **Repository & File Node Backfilling**: At application startup, a background task automatically scans ingested repositories and vault files, ensuring `Repository` and `File` graph nodes and `PART_OF` connecting edges are populated into `graph_nodes` and `graph_edges`.
2. **Expired Document Cleanup**: A periodic background worker runs every 60 seconds to purge temporary generated documents (`.docx` session summaries in `data/vault/generated/`) older than 15 minutes.
3. **Async Ingestion Jobs**: Ingestion tasks (repository cloning, AST parsing, document chunking, graphify generation) execute via FastAPI `BackgroundTasks`, logging progress to `ingestion_jobs`.

---

## 🔄 Core Ingestion Data Flows

The ingestion system processes two main input channels: **User Submission Uploads** and **GitHub Remote Codebase Ingestion**.

### 1. Document Submission Ingestion Flow
```
[User Document Upload]
         │
         ▼
[Read bytes in-memory] ──► [Parse File (Markdown, Word, PDF, Jupyter, Text)]
                                                 │
                                                 ▼
[Generate embeddings via SentenceTransformer] ◄── [Chunk text & enforce MAX_EMBEDDING_CHARS]
         │
         ▼
[Save metadata to 'documents' & chunks to 'document_chunks']
```
- **Supported Formats**: `.md`, `.txt`, `.pdf`, `.docx`, and `.ipynb`.
- **Jupyter Notebook Parser**: Specially handles JSON formats, extracting code cells and markdown cells into unified documents.

### 2. GitHub Codebase Ingestion Flow
```
[GitHub Configured Repo]
         │
         ▼
[Download zipball from API] ──► [Clone/Extract to workspace]
                                                │
                                                ▼
[Run AST analysis on files] ◄────────────────── [Collect source files]
         │
         ▼
[Run Graphify CLI command] ──► [Generate graphify-out/graph.json]
                                                │
                                                ▼
[GPT-4o batches concept extraction] ◄────────── [Map nodes and edges to MongoDB]
```
- **Graphify CLI**: The system executes `graphify extract` as a subprocess to parse the repository layout into structural files (Functions, Classes, Modules) and save them locally.
- **Node/Edge Mapping**: Parses the generated `graph.json` into MongoDB `graph_nodes` and `graph_edges`.

---

## 🧠 Local Embedding Model Integration

The platform runs local text and code embedding models in **offline mode**, eliminating external network overhead or API cost for vector generation:

- **Text Embeddings Model**: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).
- **Code Embeddings Model**: `jinaai/jina-embeddings-v2-base-code` (768 dimensions).
- **Dynamic Compatibility Patches**: Realized in `backend/app/core/embeddings.py` to patch HuggingFace's transformers config attributes (`is_decoder`, `add_cross_attention`, `get_head_mask`) and Bert tokenizers to ensure proper Jina compatibility on newer versions of PyTorch and transformers.

### Embedding Execution & Garbage Collection:
```python
# From backend/app/core/embeddings.py
from sentence_transformers import SentenceTransformer

_text_model_instance = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", trust_remote_code=True)
_code_model_instance = SentenceTransformer("jinaai/jina-embeddings-v2-base-code", trust_remote_code=True)
```
Tensors are automatically cleared using Python's garbage collector (`gc.collect()`) and CUDA cache flushing (`torch.cuda.empty_cache()`) after generation to optimize memory usage.

---

## 🔒 Authentication and Security

End-to-end security is managed via stateless JWT (JSON Web Tokens) and secure password hashing:

1. **Password Hashing**: Passwords are saved hashed using `bcrypt` (with cost factor 12) during user registration.
2. **Access Control**: Handled via FastAPI dependency injection (`require_admin`, `require_developer`, `get_current_user`) inside route definitions.
3. **Session Verification**: `get_current_user` parses the `Authorization: Bearer <token>` header, decodes the token, checks token revocation, and validates the user record.
4. **Role Matrix**: `admin` role required for system operations, repository selection/deletion, user role modification, and job management; `developer` role required for repository browsing; standard `user` access for chat and vector search.
5. **Audit Logging**: Sensitive operations write structured audit logs to the `audit_logs` collection, tracking user ID, action, resource type, detail, and timestamp.

