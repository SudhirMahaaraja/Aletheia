# Database Schema Specification

This document details the MongoDB collections used in the platform, including field types, relationship mapping, and indexing configurations.

---

## 🗃️ MongoDB Collections

The system uses a single MongoDB database (configured as `MONGODB_DB` in `.env`, defaulting to `knowledge_wiki`). The database contains the following collections:

1. **`users`**: Platform user accounts and authentication profiles.
2. **`documents`**: Metadata for uploaded source files (PDF, docx, Jupyter notebooks, Markdown).
3. **`document_chunks`**: Text content segments and text-vector embeddings for RAG retrieval.
4. **`code_chunks`**: Source code blocks and code-vector embeddings for codebase searching.
5. **`graph_nodes`**: Structural nodes in the visual knowledge graph.
6. **`graph_edges`**: Semantic and structural relationships linking nodes.
7. **`repositories`**: Configured remote GitHub codebase configurations.
8. **`ingestion_jobs`**: Job status logs for tracking background ingestion queues.
9. **`github_connections`**: GitHub integration API access tokens.

---

## 📋 Collection Schemas

### 1. `users` Collection
Stores user profiles and login credentials.
```json
{
  "_id": "ObjectId",
  "email": "string",
  "password_hash": "string",
  "role": "string (admin | user)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indexes**: Unique index on `email`.

### 2. `documents` Collection
Tracks file metadata for ingested user submissions and vault documents.
```json
{
  "_id": "string (UUID or custom string ID)",
  "title": "string",
  "original_filename": "string",
  "vault_wiki_path": "string",
  "file_type": "string (pdf | docx | ipynb | md | txt)",
  "ingestion_status": "string (pending | running | done | failed)",
  "total_chunks": "integer",
  "file_size": "integer",
  "project_name": "string (optional)",
  "repo_name": "string (optional)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### 3. `document_chunks` Collection
Stores document text segments along with their dense vectors for RAG search.
```json
{
  "_id": "string (UUID or custom chunk ID)",
  "document_id": "string (foreign key -> documents._id)",
  "document_title": "string",
  "vault_wiki_path": "string",
  "page_number": "integer",
  "content": "string",
  "embedding": "array of floats (384-dimensional vector)",
  "project_name": "string (optional)",
  "created_at": "datetime"
}
```
* **Indexes**: Single-field index on `document_id`.

### 4. `code_chunks` Collection
Stores codebase source file segments with code-oriented vectors.
```json
{
  "_id": "string (UUID or custom chunk ID)",
  "repo_name": "string (foreign key -> repositories.repo_name)",
  "file_path": "string",
  "line_start": "integer",
  "line_end": "integer",
  "content": "string",
  "embedding": "array of floats (768-dimensional vector)",
  "created_at": "datetime"
}
```
* **Indexes**: Compound index on `{ "repo_name": 1, "file_path": 1 }`.

### 5. `graph_nodes` Collection
Defines nodes in the unified knowledge graph.
```json
{
  "_id": "string (unique string ID e.g., 'Concept_d92...' or custom hex hash)",
  "type": "string (Repository | File | Class | Function | Concept | Section | Document)",
  "name": "string",
  "repo_name": "string (optional)",
  "file_path": "string (optional)",
  "language": "string (optional)",
  "summary": "string (optional)",
  "content": "string (markdown content, generated for Concept nodes)",
  "metadata": "object",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indexes**: Text index on `name`, single index on `type`, and single index on `repo_name`.

### 6. `graph_edges` Collection
Defines linkages between nodes.
```json
{
  "_id": "string (unique edge hash)",
  "from_id": "string (source node -> graph_nodes._id)",
  "to_id": "string (target node -> graph_nodes._id)",
  "type": "string (calls | implements | references | cites | conceptually_related_to | semantically_similar_to)",
  "weight": "float",
  "confidence": "string (EXTRACTED | INFERRED | AMBIGUOUS)",
  "confidence_score": "float",
  "source_file": "string (optional)",
  "created_at": "datetime"
}
```
* **Indexes**: Indexes on `from_id` and `to_id`.

### 7. `repositories` Collection
Tracks configured GitHub codebases.
```json
{
  "_id": "ObjectId",
  "name": "string (e.g. 'owner/repo')",
  "clone_url": "string",
  "branch": "string",
  "ingestion_status": "string (configured | ingested)",
  "last_ingested_at": "datetime (optional)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indexes**: Unique index on `name`.

### 8. `ingestion_jobs` Collection
Tracks items running through the asynchronous processing queue.
```json
{
  "_id": "ObjectId",
  "job_type": "string (submission | github)",
  "status": "string (pending | running | done | failed)",
  "target_id": "string (document_id or repo_name)",
  "files_processed": "integer",
  "logs": "array of strings",
  "error_message": "string (optional)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

---

## 🔗 Relationships and Constraints

The database utilizes logical pointers between collections (represented as plain strings rather than MongoDB DBRefs) which are resolved in the application controllers:

- **Chunks to Documents**: `document_chunks.document_id` links to `documents._id`. When a document is deleted by an admin, the system automatically triggers a bulk delete on `document_chunks` for all records matching `document_id`.
- **Graph Nodes to Graph Edges**: Edges use `from_id` and `to_id` to refer to node IDs in `graph_nodes`. Deleting a repository deletes all nodes matching `repo_name` and resolves inbound/outbound edges by deleting records matching those IDs in `graph_edges`.
