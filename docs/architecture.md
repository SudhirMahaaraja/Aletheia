# System Architecture and Data Flows

This document details the high-level architecture, subsystem data flows, local embedding model integrations, and security/authentication mechanisms of the platform.

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
|    OpenAI API Integration, BSON, PyPDF/Docx/ipynb)        |
+-----------------------------------------------------------+
                              │
                     MongoDB / Vector Storage
                              │
                              ▼
+-----------------------------------------------------------+
|                     MongoDB Database                      |
|   (Collections: users, documents, document_chunks,        |
|    code_chunks, graph_nodes, graph_edges)                 |
+-----------------------------------------------------------+
```

1. **Presentation Layer (React Frontend)**: Manages UI rendering, user states, chat interfaces, directory navigation, admin queues, and interactive graph visualizations (cytoscape-based). It communicates with the backend exclusively via HTTP REST endpoints.
2. **Application & Infrastructure Layer (FastAPI Backend)**: Handles route logic, authentication tokens, file parser dispatchers, code analysis, LLM completions, and vector database persistence.
3. **Database Layer (MongoDB)**: Persists all persistent state including users, parsed document metadata, code/text chunks, vectors (saved directly on the chunks for distance calculations), and graph nodes/edges.

---

## 🔄 Core Ingestion Data Flows

The ingestion system processes two main input channels: **User Submission Uploads** and **GitHub Codebase Ingestion**.

### 1. Document Submission Ingestion Flow
```
[User Document Upload]
         │
         ▼
[Save to backend/uploads/] ──► [Parse File (Markdown, Word, PDF, Jupyter)]
                                                 │
                                                 ▼
[Generate embeddings via SentenceTransformer] ◄── [Chunk text content]
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

- **Text Embeddings Model**: `sentence-transformers/all-MiniLM-L6-v2` (loaded from `./models/all-MiniLM-L6-v2`).
- **Code Embeddings Model**: `jinaai/jina-embeddings-v2-base-code` (loaded from `./models/jina-embeddings-v2-base-code`).
- **Dynamic Compatibility Patches**: Realized in `backend/app/core/embeddings.py` to patch HuggingFace's transformers config attributes (`is_decoder`, `add_cross_attention`, `get_head_mask`) and Bert tokenizers to ensure proper Jina compatibility on newer versions of PyTorch and transformers.

### Embedding Loading & Execution Pattern:
```python
# From backend/app/core/embeddings.py
from sentence_transformers import SentenceTransformer

# Load models from local cache directories
_text_model_instance = SentenceTransformer("./models/all-MiniLM-L6-v2", trust_remote_code=True)
_code_model_instance = SentenceTransformer("./models/jina-embeddings-v2-base-code", trust_remote_code=True)
```
Tensors are automatically cleared using Python's garbage collector (`gc.collect()`) and CUDA cache flushing (`torch.cuda.empty_cache()`) after generation to optimize memory usage.

---

## 🔒 Authentication and Security

End-to-end security is managed via stateless JWT (JSON Web Tokens) and secure password hashing:

1. **Password Hashing**: Passwords are saved hashed using `bcrypt` (with a cost factor of 12) during user registration.
2. **Access Control**: Handled via dependency injection inside route definitions (`backend/app/dependencies.py`).
3. **Session Verification**: The `get_current_user` dependency parses the `Authorization: Bearer <JWT>` header, decodes it, and validates the user record in the database.
4. **Role Validation**: Superadmin endpoints use checks to verify that `user.role == "admin"` before allowing destructive queue or system state edits.
