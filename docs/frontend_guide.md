# Frontend Application Guide

This document details the React frontend application built with Vite, including component modules, state contexts, interactive graph rendering, and the Ethereal Sage Design System styling guide.

---

## 📂 React Project Directory Structure

```
frontend/
├── src/
│   ├── api/              # Axios client with request/response JWT interceptors
│   ├── components/       # Common layout shells and router guards
│   ├── context/          # State management providers
│   │   ├── AuthContext.jsx
│   │   └── ChatContext.jsx
│   ├── pages/            # Page Views
│   │   ├── admin/        # Superadmin Dashboards
│   │   │   ├── Queue.jsx
│   │   │   ├── Users.jsx
│   │   │   └── Github.jsx
│   │   ├── Chat.jsx      # Chatbot interface
│   │   ├── Graph.jsx     # Interactive Knowledge Graph
│   │   ├── Wiki.jsx      # Vault Directory Browser
│   │   └── Submit.jsx    # Manual upload submission view
│   ├── App.jsx           # App entry and Route Switchboard
│   └── index.css         # Custom Ethereal Sage styling stylesheet
```

---

## 🌀 State Management Providers

1. **`AuthContext`**: Manages login/logout status, token verification, current user metadata, and authorization status (verifying if a user has the `admin` role). It intercepts Axios requests to automatically attach the JWT access token in the `Authorization: Bearer <token>` header.
2. **`ChatContext`**: Holds RAG chat sessions, active conversations, streaming/loading state flags, and message sequences.

---

## 🖼️ Primary Page Views

### 1. `Chat.jsx` (AI Assistant)
An interactive chat interface speaking to the RAG backend. When the AI returns response content, the UI processes metadata citations, rendering clickable link cards referring back to source documents and repository files.

### 2. `Graph.jsx` (Knowledge Graph View)
Renders a custom network graph using Cytoscape.js or D3.js:
- **Filtering**: Nodes can be filtered by type (Files, Repositories, Functions, Classes, Concepts).
- **Interactive Triggers**: Clicking a node selects it, highlights connected adjacent paths, and loads its content details in a side panel (including dynamic OpenAI description generations for concepts).
- **Fixes**: If the user filters or toggles categories, cytoscape retains globally connected nodes instead of discarding the graph, resolving blank graph issues.

### 3. `Wiki.jsx` (Directory Browser)
An elegant file browser layout listing directories and files in the wiki vault. It features a wide screen display to accommodate deep folder paths.

### 4. Admin Dashboards (Superadmin Views)
- **`Queue.jsx`**: Displays active ingestion jobs, status badges (pending, running, done, failed), and scrollable live logs for debug compilation checking.
- **`Github.jsx`**: Handles PAT token binding, active connection verification, and repo ingestion selector. Cards display a clear `ingestion_status` badge indicating if a repo is "Configured" (only DB schema registered) or "Ingested" (fully indexed in graph).

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
- **Interactive elements**: All buttons, badges, chips, and tag pills must use a fully rounded shape (`border-radius: 9999px`) to maintain consistency.
- **Input fields**: Form inputs use a corner radius of `8px` (`border-radius: 8px`).
- **Cards**: Surface cards use `8px` corner rounding with a thin `1px` border using `--color-outline` colors.
- **Micro-animations**: Dynamic color transitions, scale changes on hover, and active state transformations must include `transition-all duration-200 ease-in-out` modifiers.
- **User Copying**: Global text selection is fully preserved (`user-select: text`) to make code snippet extraction comfortable for engineers.
