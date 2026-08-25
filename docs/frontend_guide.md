# Frontend Application Guide

This document details the React frontend application built with Vite, including component modules, state contexts, interactive Cytoscape knowledge graph rendering, admin dashboards, and the Ethereal Sage Design System styling guide.

---

## 📂 React Project Directory Structure

```
frontend/
├── src/
│   ├── api/              # Axios client with request/response JWT interceptors & token refresh
│   ├── components/       # Layout shells, Navigation bar, and Protected Route guards
│   ├── context/          # State management providers
│   │   ├── AuthContext.jsx
│   │   └── ChatContext.jsx
│   ├── pages/            # Page Views
│   │   ├── admin/        # Superadmin Dashboards
│   │   │   ├── Queue.jsx    # Ingestion job monitoring & log viewer
│   │   │   ├── Users.jsx    # System user management & role editor
│   │   │   └── Github.jsx   # PAT connections & repository selector
│   │   ├── Chat.jsx      # Multi-mode RAG chatbot interface
│   │   ├── Graph.jsx     # Interactive Cytoscape Knowledge Graph
│   │   ├── Wiki.jsx      # Vault Directory & Markdown Page Browser
│   │   └── Submit.jsx    # Document upload submission view
│   ├── App.jsx           # Application route switcher & context provider wrappers
│   └── index.css         # Ethereal Sage design system CSS variables & utilities
```

---

## 🌀 State Management Providers

1. **`AuthContext`**: Manages user authentication state, access/refresh token persistence, active user profile (`/api/v1/auth/me`), and role-based permissions (`admin`, `developer`, `pm`). Automatically injects `Authorization: Bearer <token>` headers into outgoing Axios API requests.
2. **`ChatContext`**: Manages RAG chat session states, active session selection, message history, mode toggles (`vault_chat`, `repo_chat`, `brainstorm`), SSE streaming flags, and citation references.

---

## 🖼️ Primary Page Views

### 1. `Chat.jsx` (AI Assistant)
An interactive multi-mode chat interface communicating with `/api/v1/chat`. Features message streaming, formatted code block syntax highlighting, clickable citations linking directly to repo files or vault pages, and one-click `.docx` session export downloads.

### 2. `Graph.jsx` (Interactive Knowledge Graph View)
Renders a dynamic node-edge network graph using Cytoscape.js:
- **Filtering**: Filter nodes by type (`Repository`, `File`, `Class`, `Function`, `Concept`, `Document`, `Section`, `Project`).
- **Interactive Side Panel**: Clicking a node highlights incoming/outgoing connection edges and displays metadata, connected neighbors, and Markdown content (triggering dynamic grounded concept generation for un-cached concepts).
- **Stability**: Graph view preserves globally connected nodes during filter updates.

### 3. `Wiki.jsx` (Vault Directory Browser)
An Obsidian-style file tree and Markdown reader for navigating files under `data/vault/wiki/`. Supports internal wiki link navigation (`[[link]]`) and frontmatter metadata badges.

### 4. `Submit.jsx` (Document Upload)
Interface for uploading local documents (`.pdf`, `.docx`, `.md`, `.txt`) into selected projects.

### 5. Admin Dashboards (Superadmin Views)
- **`Queue.jsx`**: Real-time monitoring for background ingestion jobs (`/api/v1/ingest/jobs`), job logs, progress indicators, and queue job deletion.
- **`Users.jsx`**: User administration dashboard (`/api/v1/admin/users`) for listing system users, updating roles (`admin`, `developer`, `pm`), and deleting accounts.
- **`Github.jsx`**: Multi-account GitHub PAT manager (`/api/v1/github/connections`), active account toggling, repository selector (`/api/v1/github/repos`), branch inspector, and cascaded repository deletion.

---

## 🎨 Ethereal Sage Design System

The application strictly implements the **Ethereal Sage** aesthetic, structured using custom CSS variables inside `frontend/src/index.css`:

### 1. Colors & Palette
The theme toggle is controlled by writing the `data-theme` attribute to the `<html>` root node:

| Mode | Token Variable | Color / Palette | Hex Code |
|---|---|---|---|
| **Light Mode** | `--color-primary` | Forest Green | `#2f4a3b` |
| | `--color-background` | Warm Cream | `#F9F8F3` |
| | `--color-surface` | Pure White | `#ffffff` |
| | `--color-surface-container` | Off-white Cream | `#F1EFE9` |
| | `--color-on-surface` | Dark Slate | `#191c17` |
| | `--color-outline` | Muted Grey-Green | `#72796f` |
| **Dark Mode** | `--color-primary` | Vibrant Pastel Green | `#86d7a4` |
| | `--color-background` | Deep Dark Black | `#0b0d0c` |
| | `--color-surface` | Dark Charcoal | `#1c1f1d` |
| | `--color-surface-container` | Rich Grey-Green | `#262a27` |
| | `--color-on-surface` | Light Slate | `#e2e8f0` |
| | `--color-outline` | Cool Slate | `#8a9389` |

### 2. Layout Rules
- **Interactive elements**: All buttons, badges, chips, and tag pills must use a fully rounded shape (`border-radius: 9999px`) to maintain visual consistency.
- **Input fields**: Form inputs use a corner radius of `8px` (`border-radius: 8px`).
- **Cards**: Surface cards use `8px` corner rounding with a thin `1px` border using `--color-outline` colors.
- **Micro-animations**: Dynamic color transitions, scale changes on hover, and active state transformations must include `transition-all duration-200 ease-in-out` modifiers.
- **User Copying**: Global text selection is fully preserved (`user-select: text`) to make code snippet extraction comfortable for engineers.

