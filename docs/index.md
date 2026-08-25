# Aletheia - Developer Documentation Index

> *The act of revealing what is hidden*

Welcome to the technical documentation for **Aletheia**, an internal knowledge vault, code-graph ingestion engine, and retrieval-augmented AI assistant (RAG). This directory acts as the central hub for understanding the codebase, system workflows, database models, REST API specifications, and deployment configurations.

## Documentation Sections

1. **[System Architecture](architecture.md)**
   - High-level architecture summary & decoupled component layers.
   - Dual vector embedding models & local HuggingFace patch integration.
   - Core ingestion data flows (Document Upload, GitHub Ingestion).
   - FastAPI Lifespan & background worker tasks.
   - Authentication flow & role-based authorization security.

2. **[Database Schema](database_schema.md)**
   - Comprehensive model definitions for all 13 MongoDB collections (`users`, `documents`, `document_chunks`, `code_chunks`, `graph_nodes`, `graph_edges`, `repositories`, `ingestion_jobs`, `github_connections`, `audit_logs`, `chat_sessions`, `chat_messages`, `projects`).
   - Document metadata, code chunks, knowledge graph structure, and index definitions (unique, TTL, text).

3. **[REST API Specification](api_specification.md)**
   - Complete endpoint developer reference versioned under `/api/v1/*`.
   - Specifications for Authentication, GitHub Connections, Ingestion & Projects, RAG Chat & Sessions, Vector Search, Knowledge Graph, and Superadmin Operations.

4. **[Ingestion & Graph Generation Pipeline](ingestion_and_graph.md)**
   - AST code parsers (Python, JavaScript/TypeScript, SQL) and document parsers (PDF, DOCX, Markdown, Text, Jupyter Notebooks).
   - Chunker sizing constraints (`MAX_EMBEDDING_CHARS`).
   - Graphify CLI integration, syntax tree extraction, and node/edge storage.
   - Batch LLM concept extraction and dynamic grounded concept page generation via GPT-4o.

5. **[Frontend Application Guide](frontend_guide.md)**
   - React application structure, Vite build system, state context providers (`AuthContext`, `ChatContext`).
   - Page view specifications (`Chat.jsx`, `Graph.jsx`, `Wiki.jsx`, `Submit.jsx`, `Queue.jsx`, `Users.jsx`, `Github.jsx`).
   - Cytoscape-based interactive network graph rendering.
   - Ethereal Sage Design System specification, color palettes (Light & Dark), and layout styling tokens.

6. **[Deployment & Setup Guide](deployment_setup.md)**
   - System prerequisites (Python 3.10+, Node.js 18+, MongoDB).
   - Environment variables (`.env`) reference.
   - Local developer startup commands and server endpoint details.
   - Windows environment paths and Graphify CLI execution notes.

---
*Generated internally for the engineering team. Maintain these files in sync with any major architectural or pipeline changes.*

