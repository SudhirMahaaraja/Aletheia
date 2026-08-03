# Aletheia - Developer Documentation Index

> *The act of revealing what is hidden*

Welcome to the technical documentation for **Aletheia**, an internal knowledge vault and retrieval-augmented AI assistant. This directory acts as the central hub for understanding the codebase, system workflows, database models, and deployment configurations.

## Documentation Sections

1. **[System Architecture](architecture.md)**
   - High-level architecture summary.
   - Decoupled client-server structure.
   - Authentication flow & RAG embedding pipeline integration.

2. **[Database Schema](database_schema.md)**
   - Comprehensive model definitions for all MongoDB collections.
   - Document metadata, code chunks, and knowledge graph structure.

3. **[REST API Specification](api_specification.md)**
   - Developer documentation of all endpoints for Authentication, Submissions, GitHub, Wiki, Graph, and RAG Chat.

4. **[Ingestion & Graph Generation Pipeline](ingestion_and_graph.md)**
   - Details of the background parsing & chunking workflows.
   - Graphify CLI integration, AST parsing, and batch concept extraction prompts.
   - Dynamic concept page generation logic.

5. **[Frontend Application Guide](frontend_guide.md)**
   - React application structure, Vite build system, state context providers.
   - Obsidian-style network graph rendering.
   - Ethereal Sage Design System, colors, typography, layout styling.

6. **[Deployment & Setup Guide](deployment_setup.md)**
   - Installation requirements, local developer startup, Windows configurations.
   - Environment variables (`.env`) reference.

---
*Generated internally for the engineering team. Maintain these files in sync with any major architectural or pipeline changes.*
