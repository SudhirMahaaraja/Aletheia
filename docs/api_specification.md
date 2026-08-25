# REST API Specification

This document details the HTTP REST endpoints exposed by the Aletheia backend API. All API routes are versioned under `/api/v1` (unless otherwise noted).

---

## 🔒 Authentication (`/api/v1/auth`)

Endpoints for user registration, authentication tokens, session management, and user profiles.

### 1. Register User Account
* **Method**: `POST`
* **Path**: `/api/v1/auth/register`
* **Auth Requirement**: JWT Access Token with `admin` role
* **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "strongpassword123",
    "full_name": "Jane Doe",
    "role": "developer"
  }
  ```
* **Response**: `200 OK` (returns user profile DTO).

### 2. Login
* **Method**: `POST`
* **Path**: `/api/v1/auth/login`
* **Auth Requirement**: None
* **Request Format**: `application/x-www-form-urlencoded`
  - `username`: string (user email address)
  - `password`: string
* **Response**: `200 OK`
  ```json
  {
    "access_token": "eyJhbGciOi...",
    "refresh_token": "eyJhbGciOi...",
    "token_type": "bearer"
  }
  ```

### 3. Refresh Access Token
* **Method**: `POST`
* **Path**: `/api/v1/auth/refresh`
* **Auth Requirement**: None
* **Request Body**:
  ```json
  {
    "refresh_token": "eyJhbGciOi..."
  }
  ```
* **Response**: `200 OK` with fresh `access_token` and `refresh_token`.

### 4. Logout
* **Method**: `POST`
* **Path**: `/api/v1/auth/logout`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "refresh_token": "eyJhbGciOi..."
  }
  ```
* **Response**: `200 OK` (`{"message": "logged out"}`). Revokes refresh token in database.

### 5. Get Current User Profile
* **Method**: `GET`
* **Path**: `/api/v1/auth/me`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (user profile data: `user_id`, `email`, `full_name`, `role`, `is_active`, `created_at`).

---

## 🐙 GitHub Integration (`/api/v1/github`)

Endpoints for configuring GitHub connections, inspecting branches, selecting repositories, and performing cascaded repository deletions.

### 1. Connect GitHub Account / PAT
* **Method**: `POST`
* **Path**: `/api/v1/github/connect`
* **Auth Requirement**: `admin` role
* **Request Body**:
  ```json
  {
    "pat": "ghp_yourpersonalaccesstokenhere",
    "org_name": "optional_organization_name"
  }
  ```
* **Response**: `200 OK` (validates PAT token with GitHub API and sets connection as active).

### 2. List GitHub Connections
* **Method**: `GET`
* **Path**: `/api/v1/github/connections`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK` (list of registered GitHub connection accounts and active state).

### 3. Activate Connection
* **Method**: `POST`
* **Path**: `/api/v1/github/connections/activate`
* **Auth Requirement**: `admin` role
* **Request Body**:
  ```json
  {
    "user_login": "github_username",
    "org_name": "optional_org"
  }
  ```
* **Response**: `200 OK`.

### 4. Delete Connection
* **Method**: `DELETE`
* **Path**: `/api/v1/github/connections`
* **Auth Requirement**: `admin` role
* **Query Parameters**: `user_login`, `org_name`
* **Response**: `200 OK`.

### 5. List Selectable Repositories
* **Method**: `GET`
* **Path**: `/api/v1/github/repos`
* **Auth Requirement**: `developer` or `admin` role
* **Response**: `200 OK` (returns list of repositories from GitHub API combined with database selection status).

### 6. Get Repository Branches
* **Method**: `GET`
* **Path**: `/api/v1/github/repos/{repo_full_name:path}/branches`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK` (list of branch names, e.g., `["main", "develop", "feature/rag"]`).

### 7. Select Repository for Ingestion
* **Method**: `POST`
* **Path**: `/api/v1/github/repos/select`
* **Auth Requirement**: `admin` role
* **Request Body**:
  ```json
  {
    "repo_full_name": "owner/repo",
    "branch": "main"
  }
  ```
* **Response**: `200 OK` (registers repository in MongoDB for ingestion).

### 8. Deselect Repository
* **Method**: `DELETE`
* **Path**: `/api/v1/github/repos/{repo_full_name:path}/deselect`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK`.

### 9. Delete Ingested Repository (Cascaded Delete)
* **Method**: `DELETE`
* **Path**: `/api/v1/github/repos/{repo_full_name:path}`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK` (deletes code chunks, documents, graph nodes, graph edges, database repository records, and local vault folders, then rebuilds vault index).

---

## 🏗️ Ingestion & Projects (`/api/v1/ingest`)

Endpoints for triggering repository ingestion pipelines, document uploads, project management, and tracking background jobs.

### 1. Ingest Repository to DB
* **Method**: `POST`
* **Path**: `/api/v1/ingest/repo`
* **Auth Requirement**: `admin` role
* **Request Body**:
  ```json
  {
    "repo_full_name": "owner/repo"
  }
  ```
* **Response**: `200 OK` with background `job_id` and queued status.

### 2. Ingest Repository to Local Vault & DB
* **Method**: `POST`
* **Path**: `/api/v1/ingest/repo-to-vault`
* **Auth Requirement**: `admin` role
* **Request Body**:
  ```json
  {
    "repo_full_name": "owner/repo"
  }
  ```
* **Response**: `200 OK` with background `job_id` and queued status.

### 3. Upload Document
* **Method**: `POST`
* **Path**: `/api/v1/ingest/document`
* **Auth Requirement**: JWT Access Token
* **Request Format**: `multipart/form-data`
  - `file`: Uploaded file binary (`.pdf`, `.docx`, `.md`, `.txt`)
  - `title`: string (optional)
  - `project_id`: string (optional)
* **Response**: `200 OK` (`job_id`, `document_id`, `status`).

### 4. Delete Document (Cascaded Delete)
* **Method**: `DELETE`
* **Path**: `/api/v1/ingest/document/{document_id}`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK` (removes document record, document chunks, graph nodes/edges, and vault raw/wiki files).

### 5. List Ingestion Jobs
* **Method**: `GET`
* **Path**: `/api/v1/ingest/jobs`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (list of recent ingestion jobs with file counts, created nodes/edges, and log arrays).

### 6. Get Job Details
* **Method**: `GET`
* **Path**: `/api/v1/ingest/jobs/{job_id}`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (job status, processed file count, error messages, log list, and current file name).

### 7. Delete Ingestion Job
* **Method**: `DELETE`
* **Path**: `/api/v1/ingest/jobs/{job_id}`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK`.

### 8. List Projects
* **Method**: `GET`
* **Path**: `/api/v1/ingest/projects`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (list of project DTOs).

### 9. Create Project
* **Method**: `POST`
* **Path**: `/api/v1/ingest/projects`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "name": "Backend RAG Redesign",
    "description": "Project workspace for indexing backend documentation"
  }
  ```
* **Response**: `201 Created` (creates project record and corresponding `Project` graph node).

---

## 💬 RAG Chatbot Assistant (`/api/v1/chat`)

Endpoints for managing multi-mode RAG chat sessions, streaming response completions, and exporting sessions.

### 1. Create Chat Session
* **Method**: `POST`
* **Path**: `/api/v1/chat/sessions`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "title": "Architecture Overview Chat",
    "mode": "repo_chat",
    "repo_name": "owner/repo"
  }
  ```
* **Response**: `200 OK` with session details.

### 2. List Chat Sessions
* **Method**: `GET`
* **Path**: `/api/v1/chat/sessions`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (list of active user chat sessions).

### 3. Get Chat Session Details & Messages
* **Method**: `GET`
* **Path**: `/api/v1/chat/sessions/{session_id}`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (session metadata and full message history).

### 4. Delete Chat Session
* **Method**: `DELETE`
* **Path**: `/api/v1/chat/sessions/{session_id}`
* **Auth Requirement**: JWT Access Token
* **Response**: `204 No Content`.

### 5. Send Message (RAG Query)
* **Method**: `POST`
* **Path**: `/api/v1/chat/sessions/{session_id}/message`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "message": "Explain how AST chunking works in the ingestion pipeline."
  }
  ```
* **Response**: `200 OK` (returns AI assistant response, vector search citations, and code snippet references).

### 6. Download Chat Session Summary as Word Document
* **Method**: `GET`
* **Path**: `/api/v1/chat/sessions/{session_id}/download-docx`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (returns `.docx` file stream of formatted session transcript).

---

## 🔍 Semantic Vector Search (`/api/v1/search`)

### 1. Search Vector Space
* **Method**: `POST`
* **Path**: `/api/v1/search/`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "query": "mongodb index initialization",
    "target": "all",
    "repo_name": "owner/repo",
    "top_k": 5
  }
  ```
* **Response**: `200 OK` (matching code and document chunk results with similarity scores).

---

## 🕸️ Knowledge Graph (`/api/v1/graph`)

### 1. List Graph Nodes
* **Method**: `GET`
* **Path**: `/api/v1/graph/nodes`
* **Auth Requirement**: JWT Access Token
* **Query Parameters**: `repo_name`, `node_type`
* **Response**: `200 OK` (returns list of node metadata).

### 2. List Graph Edges
* **Method**: `GET`
* **Path**: `/api/v1/graph/edges`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (returns list of directional edges).

### 3. Get Node Details and Generate Content
* **Method**: `GET`
* **Path**: `/api/v1/graph/nodes/{node_id:path}`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (node metadata, 1-depth neighbors, connecting edges, and Markdown content).
* *Note*: Un-cached `Concept` nodes trigger dynamic grounded GPT-4o generation.

---

## 🛠️ Superadmin Operations (`/api/v1/admin`)

Endpoints restricted strictly to users with the `admin` role.

### 1. List System Users
* **Method**: `GET`
* **Path**: `/api/v1/admin/users`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK` (list of registered user accounts and roles).

### 2. Update User Role
* **Method**: `PATCH`
* **Path**: `/api/v1/admin/users/{user_id}/role`
* **Auth Requirement**: `admin` role
* **Request Body**:
  ```json
  {
    "role": "admin"
  }
  ```
* **Response**: `200 OK` with updated user DTO.

### 3. Delete User Account
* **Method**: `DELETE`
* **Path**: `/api/v1/admin/users/{user_id}`
* **Auth Requirement**: `admin` role
* **Response**: `204 No Content`.

### 4. List Audit Logs
* **Method**: `GET`
* **Path**: `/api/v1/admin/audit-logs`
* **Auth Requirement**: `admin` role
* **Query Parameters**: `skip` (default 0), `limit` (default 100)
* **Response**: `200 OK` (list of system audit log entries).

### 5. Get System Statistics
* **Method**: `GET`
* **Path**: `/api/v1/admin/stats`
* **Auth Requirement**: `admin` role
* **Response**: `200 OK`
  ```json
  {
    "total_users": 12,
    "total_repos": 3,
    "total_documents": 45,
    "total_chunks_code": 1420,
    "total_chunks_docs": 310,
    "total_graph_nodes": 850,
    "total_graph_edges": 1940,
    "active_jobs": 0
  }
  ```

