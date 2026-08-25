# Ingestion and Graph Generation Pipeline

This document explains the technical details of document parsing, AST code analysis, structural knowledge graph extraction, and dynamic concept documentation pipelines in Aletheia.

---

## 📄 Document Parsing and Chunking

When a document or source file is uploaded or ingested from the vault, it passes through specialized parsers located in `backend/app/controllers/ingestion/parsers/`:

1. **PDF Files (`fitz` / `PyMuPDF`)**: Groups every 2 pages of extracted text into a unified chunk, preserving page numbers in metadata (`page_number`).
2. **Word Documents (`docx`)**: Parses paragraphs, grouping text by Heading styles (e.g., `Heading 1`, `Heading 2`). If no headings are present, paragraphs are grouped in blocks of 10.
3. **Markdown (`.md`)**: Splits documents dynamically by H2 level headings (`## `) to preserve logical topic separation.
4. **Text Files (`.txt`)**: Processes files in batches of 800 words. If the file is identified as a `README`, the minimum length threshold is bypassed to capture all overview details.
5. **Jupyter Notebooks (`.ipynb`)**: Parsed cell-by-cell from raw JSON, concatenating code cells and Markdown cells into structured readable logs.

### Chunker Sizing Guardrail:
After initial parsing, all chunks are post-processed through `split_chunk_by_lines` which enforces a character ceiling matching `MAX_EMBEDDING_CHARS` (configured in `.env`, defaulting to `2000`). If a chunk exceeds this length, it is split along line breaks to avoid cutting sentences.

---

## 🐙 Codebase Parsing & Graphify CLI Integration

When a remote repository is ingested, the system extracts structural symbol relationships (Classes, Functions, Modules):

1. **Workspace Extraction**: Clones the repo zipball and extracts it to a local temporary workspace directory.
2. **Subprocess Invocation**: The backend executes the external CLI binary `graphify` (as defined in `backend/app/controllers/ingestion/graph_builder.py`):
   ```bash
   graphify extract <repo_dir> --backend azure --out <repo_dir>
   ```
3. **Parsing AST JSON**: Graphify parses the syntax tree of code files (`.py`, `.js`, `.ts`, `.sql`) and writes a local `graphify-out/graph.json` mapping entities (Function names, Classes, Modules) and explicit relationships (e.g., `calls`, `implements`, `references`).
4. **MongoDB Storage**: The backend parses `graph.json`, maps nodes to `graph_nodes` (generating unique SHA-256 string IDs from `{repo_name}:{file_path}:{name}:{g_type}`), and maps edges to `graph_edges`.
5. **Background Node Sync**: At startup and post-ingestion, background tasks generate `Repository` and `File` graph nodes linked with `PART_OF` edges.

---

## 🧠 LLM Concept Extraction & Grounding

The platform utilizes OpenAI's GPT-4o model to extract abstract terms and generate grounded concept documentation.

### 1. Ingestion Concept Extraction (Batch)
During repository parsing, code chunks are processed in batches of 10. The backend calls GPT-4o with `CONCEPT_EXTRACTION_PROMPT` to identify specific technologies and concepts:

* **Prompt Rules**:
  - Focus strictly on repository-specific, concrete implementations.
  - Exclude general concepts or generic design patterns unless there is a custom, specific configuration in the code.
  - Extract only terms that are directly visible in the code text.

### 2. On-Demand Concept Page Generation (Dynamic)
When a user requests a `Concept` node via `/api/v1/graph/nodes/{node_id:path}`, if it does not have cached Markdown content, the endpoint dynamically invokes GPT-4o using the surrounding code/text chunk references:

* **Prompt Grounding Rules**:
  - The model must explain the concept *strictly* within the context of the provided code blocks.
  - Generics and external tutorials (e.g., standard Iris dataset examples, general library tutorials) are strictly prohibited.
  - All referenced code blocks, variables, classes, database schemas, and configuration parameters must be derived directly from the visible codebase files.
  - This ensures that concept descriptions accurately reflect how they are implemented in the specific project.

