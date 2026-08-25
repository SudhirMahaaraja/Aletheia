# Database Schema Specification

This document details the MongoDB collections used in the Aletheia platform, including field types, indexing configurations, and logical relationship mappings.

---

## 🗃️ MongoDB Collections

The system uses an asynchronous MongoDB database (configured as `MONGO_DB_NAME` in `.env`, defaulting to `aletheia_db`). The database contains the following 13 collections:

1. **`users`**: Platform user accounts and authentication profiles.
2. **`documents`**: Metadata for uploaded source files (PDF, DOCX, Jupyter notebooks, Markdown, TXT).
3. **`document_chunks`**: Text content segments and dense text-vector embeddings (384d) for RAG retrieval.
4. **`code_chunks`**: Source code blocks and dense code-vector embeddings (768d) for codebase searching.
5. **`graph_nodes`**: Structural nodes in the visual knowledge graph.
6. **`graph_edges`**: Semantic and structural relationships linking graph nodes.
7. **`repositories`**: Configured GitHub codebase configurations and ingestion status.
8. **`ingestion_jobs`**: Job queue tracking background repository and document ingestion tasks.
9. **`github_connections`**: GitHub integration PAT tokens and connection profiles.
10. **`audit_logs`**: System audit logs recording administrative and security actions.
11. **`chat_sessions`**: Chat session conversations and RAG configuration parameters.
12. **`chat_messages`**: Message history and AI response citations per chat session.
13. **`projects`**: Project workspace groupings for organizing documents and knowledge.

---

## 📋 Collection Schemas

### 1. `users` Collection
Stores user profiles and login credentials.
```json
{
  "_id": "ObjectId",
  "email": "string",
  "password_hash": "string",
  "full_name": "string",
  "role": "string (admin | developer | pm)",
  "is_active": "boolean",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indexes**: Unique index on `email`.

### 2. `documents` Collection
Tracks file metadata for ingested user submissions and vault documents.
```json
{
  "_id": "string (UUID / ObjectId string)",
  "title": "string",
  "original_filename": "string",
  "file_type": "string (pdf | docx | ipynb | md | txt)",
  "project_id": "string (optional foreign key -> projects._id)",
  "repo_name": "string (optional)",
  "vault_raw_path": "string (optional)",
  "vault_wiki_path": "string (optional)",
  "uploaded_by": "string (foreign key -> users._id)",
  "uploaded_at": "datetime",
  "ingestion_status": "string (queued | processing | done | failed)",
  "total_chunks": "integer",
  "file_size_bytes": "integer"
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
  "page_number": "integer (optional)",
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
  "repo_name": "string (foreign key -> repositories.github_full_name)",
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
  "_id": "string (unique hex string hash, e.g. SHA-256 hash)",
  "type": "string (Repository | File | Class | Function | Concept | Section | Document | Project)",
  "name": "string",
  "repo_name": "string (optional)",
  "file_path": "string (optional)",
  "language": "string (optional)",
  "summary": "string (optional)",
  "content": "string (markdown content, dynamically generated or cached)",
  "metadata": "object",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
* **Indexes**: Text index on `name`, single index on `type`, and single index on `repo_name`.

### 6. `graph_edges` Collection
Defines directional linkages between graph nodes.
```json
{
  "_id": "string (unique edge hash)",
  "from_id": "string (source node -> graph_nodes._id)",
  "to_id": "string (target node -> graph_nodes._id)",
  "type": "string (calls | implements | references | cites | PART_OF | conceptually_related_to)",
  "weight": "float",
  "confidence": "string (EXTRACTED | INFERRED | AMBIGUOUS)",
  "confidence_score": "float",
  "source_file": "string (optional)",
  "created_at": "datetime"
}
```
* **Indexes**: Single-field indexes on `from_id` and `to_id`.

### 7. `repositories` Collection
Tracks configured remote GitHub codebases.
```json
{
  "_id": "ObjectId",
  "github_full_name": "string (e.g. 'owner/repo')",
  "name": "string",
  "description": "string",
  "language": "string",
  "selected_branch": "string",
  "is_selected": "boolean",
  "ingestion_status": "string (never | queued | processing | done | failed)",
  "total_files": "integer",
  "total_chunks": "integer",
  "added_at": "datetime"
}
```
* **Indexes**: Unique index on `github_full_name`.

### 8. `ingestion_jobs` Collection
Tracks tasks running through the asynchronous background queue.
```json
{
  "_id": "string (ObjectId string)",
  "job_type": "string (repo | vault_repo | document)",
  "source_id": "string (repository _id or document_id)",
  "source_name": "string",
  "status": "string (queued | processing | done | failed)",
  "files_total": "integer",
  "files_processed": "integer",
  "chunks_created": "integer",
  "nodes_created": "integer",
  "edges_created": "integer",
  "errors": "array of strings",
  "current_file": "string (optional)",
  "started_at": "datetime",
  "completed_at": "datetime",
  "triggered_by": "string (foreign key -> users._id)"
}
```

### 9. `github_connections` Collection
Stores GitHub API personal access tokens and active account states.
```json
{
  "_id": "ObjectId",
  "user_login": "string",
  "org_name": "string",
  "pat": "string",
  "active": "boolean",
  "updated_at": "datetime"
}
```

### 10. `audit_logs` Collection
Records security actions and admin changes.
```json
{
  "_id": "ObjectId",
  "user_id": "string (foreign key -> users._id)",
  "action": "string (login | user_role_change | user_delete | document_upload | repo_delete)",
  "resource_type": "string (user | document | repository)",
  "resource_id": "string",
  "detail": "string",
  "ip_address": "string",
  "created_at": "datetime"
}
```
* **Indexes**: 90-day TTL index on `created_at` (`expireAfterSeconds: 7776000`).

### 11. `chat_sessions` Collection
Stores RAG chat assistant conversation metadata.
```json
{
  "_id": "string (ObjectId string)",
  "user_id": "string (foreign key -> users._id)",
  "title": "string",
  "mode": "string (vault_chat | repo_chat | brainstorm)",
  "repo_name": "string (optional)",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### 12. `chat_messages` Collection
Stores individual user and assistant messages per chat session.
```json
{
  "_id": "ObjectId",
  "session_id": "string (foreign key -> chat_sessions._id)",
  "role": "string (user | assistant)",
  "content": "string",
  "citations": "array of objects (source references & line numbers)",
  "created_at": "datetime"
}
```

### 13. `projects` Collection
Groups documents and workspace files under project titles.
```json
{
  "_id": "string (ObjectId string)",
  "name": "string",
  "description": "string",
  "created_at": "datetime"
}
```
* **Indexes**: Unique index on `name`.

---

## 🔗 Relationships and Cascaded Deletions

The database utilizes logical pointers between collections which are resolved in application controllers:

- **Document Cascaded Delete**: Deleting a document (`DELETE /api/v1/ingest/document/{document_id}`) triggers bulk removal of matching `document_chunks`, associated `Section` graph nodes, connecting `graph_edges`, database `documents` record, and local vault files (`vault_raw_path`, `vault_wiki_path`).
- **Repository Cascaded Delete**: Deleting an ingested repository (`DELETE /api/v1/github/repos/{repo_full_name}`) triggers bulk removal of matching `code_chunks`, associated documents and `document_chunks`, repository graph nodes and edges (`graph_nodes`, `graph_edges`), `repositories` collection entry, and local vault directories (`raw/`, `wiki/`, `graphs/`).

