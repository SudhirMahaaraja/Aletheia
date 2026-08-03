# REST API Specification

This document details the HTTP REST endpoints exposed by the backend API. All API routes are versioned under `/api/v1` (unless otherwise noted).

---

## 🔒 Authentication (`/api/v1/auth`)

Endpoints for managing user accounts, authentication tokens, and user profiles.

### 1. Register User
* **Method**: `POST`
* **Path**: `/api/v1/auth/register`
* **Auth Requirement**: None
* **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "strongpassword123"
  }
  ```
* **Response**: `200 OK` (returns user metadata without password hashes).

### 2. Login
* **Method**: `POST`
* **Path**: `/api/v1/auth/login`
* **Auth Requirement**: None
* **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "strongpassword123"
  }
  ```
* **Response**: `200 OK` with access and refresh tokens.

### 3. Get Current User Profile
* **Method**: `GET`
* **Path**: `/api/v1/auth/me`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (user profile data, e.g., role, email, active state).

---

## 🏗️ Ingestion (`/api/v1/ingest`)

Endpoints for handling document uploads, vault submissions, and repository indexing runs.

### 1. Upload Submission Document
* **Method**: `POST`
* **Path**: `/api/v1/ingest/document`
* **Auth Requirement**: JWT Access Token
* **Request Format**: `multipart/form-data`
  - `file`: Uploaded file binary (PDF, docx, Jupyter notebook, Markdown, txt)
  - `project_name`: string (optional)
* **Response**: `200 OK` with generated document ID and ingestion job ID.

### 2. Get Ingestion Jobs
* **Method**: `GET`
* **Path**: `/api/v1/ingest/jobs`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (list of active and completed ingestion jobs).

### 3. Get Job Details
* **Method**: `GET`
* **Path**: `/api/v1/ingest/jobs/{job_id}`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (job status, processed file count, error messages, and log list).

### 4. Delete Document
* **Method**: `DELETE`
* **Path**: `/api/v1/ingest/document/{document_id}`
* **Auth Requirement**: JWT Access Token (Superadmin only)
* **Response**: `200 OK` (document metadata and corresponding chunks removed from database).

---

## 🐙 GitHub Integration (`/api/v1/github`)

Endpoints for configuring GitHub connections, fetching repo trees, and selecting repositories for ingestion.

### 1. Connect GitHub Account
* **Method**: `POST`
* **Path**: `/api/v1/github/connect`
* **Auth Requirement**: JWT Access Token (Superadmin only)
* **Request Body**:
  ```json
  {
    "pat_token": "ghp_yourpersonalaccesstokenhere"
  }
  ```
* **Response**: `200 OK` (validates connection with GitHub API and persists credentials).

### 2. Select Repository for Ingestion
* **Method**: `POST`
* **Path**: `/api/v1/github/repos/select`
* **Auth Requirement**: JWT Access Token (Superadmin only)
* **Request Body**:
  ```json
  {
    "repo_name": "owner/repo",
    "branch": "main"
  }
  ```
* **Response**: `200 OK` (saves configuration and schedules background pipeline indexing).

### 3. List Selectable Repositories
* **Method**: `GET`
* **Path**: `/api/v1/github/repos`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (returns list of repositories from the connected GitHub profile).

---

## 🕸️ Knowledge Graph (`/api/v1/graph`)

Endpoints for retrieving structural nodes, semantic edges, and dynamically generating concept details.

### 1. List Graph Nodes
* **Method**: `GET`
* **Path**: `/api/v1/graph/nodes`
* **Auth Requirement**: JWT Access Token
* **Query Parameters**:
  - `repo_name`: string (optional, filter nodes by repository)
  - `node_type`: string (optional, filter by `Repository`, `File`, `Class`, `Function`, `Concept`, `Document`, `Section`)
* **Response**: `200 OK` (returns list of node metadata).

### 2. List Graph Edges
* **Method**: `GET`
* **Path**: `/api/v1/graph/edges`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (returns list of directional edges linking the nodes).

### 3. Get Node Details and Generate Content
* **Method**: `GET`
* **Path**: `/api/v1/graph/nodes/{node_id:path}`
* **Auth Requirement**: JWT Access Token
* **Response**: `200 OK` (returns node schema, list of 1-depth neighbors, connecting edges, and Markdown content).
* *Note*: If the target node is a `Concept` and the Markdown `content` is missing from MongoDB, the backend dynamically queries OpenAI (gpt-4o) to generate a premium description strictly grounded in the codebase context before returning the response.

---

## 💬 RAG Chatbot Assistant (`/api/v1/chat`)

Endpoints for managing chat conversations and querying the company vector space.

### 1. Create Chat Session
* **Method**: `POST`
* **Path**: `/api/v1/chat/sessions`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "title": "New Session Title"
  }
  ```
* **Response**: `201 Created` with generated session ID.

### 2. Send Message (RAG Query)
* **Method**: `POST`
* **Path**: `/api/v1/chat/sessions/{session_id}/message`
* **Auth Requirement**: JWT Access Token
* **Request Body**:
  ```json
  {
    "message": "Explain how the Singleton class is configured in the repository."
  }
  ```
* **Response**: `200 OK` (returns AI assistant message text, matching citations, and source references).

---

## 🛠️ Superadmin Operations (`/api/v1/admin`)

Endpoints restricted strictly to users with the `admin` role.

### 1. List System Users
* **Method**: `GET`
* **Path**: `/api/v1/admin/users`
* **Auth Requirement**: JWT Access Token (Superadmin only)
* **Response**: `200 OK` (list of registered user accounts and active roles).

### 2. Update User Role
* **Method**: `PATCH`
* **Path**: `/api/v1/admin/users/{user_id}/role`
* **Auth Requirement**: JWT Access Token (Superadmin only)
* **Request Body**:
  ```json
  {
    "role": "admin"
  }
  ```
* **Response**: `200 OK` with updated profile.
