from __future__ import annotations

import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from app.controllers.ingestion.parsers.base_parser import ParsedChunk


AGENTS_TEMPLATE = """# Wiki Maintainer Schema

This vault follows a three-layer workflow:

1. raw/ stores immutable source material copied from repositories and uploaded documents.
2. wiki/ stores generated markdown notes, summaries, indexes, and logs.
3. graphify-out/ stores graph artifacts generated from the wiki layer.

Operational rules:
- Never edit files under raw/.
- Add new synthesized notes under wiki/.
- Update wiki/index.md and wiki/log.md whenever a source is ingested.
- Prefer linking related notes instead of duplicating long passages.
- Treat repository overviews and document notes as durable pages that can be refined over time.
"""


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._/-]+", "-", value.strip())
    value = value.replace("\\", "/")
    value = value.replace("/", "-")
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-._")
    return value or "item"


def repo_slug(repo_full_name: str) -> str:
    return "--".join(slugify(part) for part in repo_full_name.split("/") if part.strip()) or "repository"


def resolve_vault_dir(vault_path: str = "") -> Path:
    if vault_path.strip():
        return Path(vault_path).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "data" / "vault"
        if candidate.is_dir():
            return candidate

    for parent in current.parents:
        candidate = parent / "vault"
        if candidate.is_dir():
            return candidate

    for parent in current.parents:
        if (parent / "binarywaves-wiki").is_dir():
            return parent / "binarywaves-wiki" / "backend" / "data" / "vault"

    return Path(r"d:\Wiki\binarywaves-wiki\backend\data\vault")


def ensure_vault_structure(vault_dir: Path) -> dict[str, Path]:
    paths = {
        "root": vault_dir,
        "raw_root": vault_dir.parent / "raw",
        "raw_repositories": vault_dir.parent / "raw" / "repositories",
        "raw_documents": vault_dir.parent / "raw" / "documents",
        "wiki_root": vault_dir / "wiki",
        "wiki_repositories": vault_dir / "wiki" / "repositories",
        "wiki_documents": vault_dir / "wiki" / "documents",
        "graphs_root": vault_dir.parent / "graphs",
        "repo_graphs": vault_dir.parent / "graphs" / "repositories",
    }

    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    agents_path = vault_dir / "AGENTS.md"
    if not agents_path.exists():
        agents_path.write_text(AGENTS_TEMPLATE.strip() + "\n", encoding="utf-8")

    return paths


def reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def copy_file(source: str | Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), destination)


def markdown_language(ext: str) -> str:
    return ext[1:] if ext.startswith(".") else (ext or "text")


def render_repo_source_page(
    repo_full_name: str,
    rel_path: str,
    raw_rel_path: str,
    content: str,
    ext: str,
) -> str:
    title = Path(rel_path).name
    if ext == ".md":
        body = content
    else:
        body = f"```{markdown_language(ext)}\n{content}\n```"

    return (
        f"---\n"
        f"type: repo-source\n"
        f"repository: {repo_full_name}\n"
        f"source_path: {rel_path}\n"
        f"raw_path: {raw_rel_path}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"- Repository: `{repo_full_name}`\n"
        f"- Source path: `{rel_path}`\n"
        f"- Raw copy: `{raw_rel_path}`\n\n"
        f"{body}\n"
    )


def _summarize_repo_files(rel_paths: Sequence[str]) -> tuple[list[str], list[str]]:
    ext_counts = Counter(Path(path).suffix.lower() or "<none>" for path in rel_paths)
    dir_counts = Counter((Path(path).parts[0] if len(Path(path).parts) > 1 else "(root)") for path in rel_paths)

    ext_summary = [
        f"`{ext}`: {count}"
        for ext, count in ext_counts.most_common(8)
    ]
    dir_summary = [
        f"`{directory}`: {count}"
        for directory, count in dir_counts.most_common(8)
    ]
    return ext_summary, dir_summary


def write_repo_overview(
    wiki_repo_dir: Path,
    repo_full_name: str,
    branch: str,
    rel_paths: Sequence[str],
    repo_graph_dir: Path,
) -> Path:
    ext_summary, dir_summary = _summarize_repo_files(rel_paths)
    source_links = "\n".join(
        f"- [{path}](sources/{path}.md)"
        for path in sorted(rel_paths)[:200]
    )
    if len(rel_paths) > 200:
        source_links += f"\n- ... and {len(rel_paths) - 200} more source notes"

    graph_rel = repo_graph_dir.relative_to(wiki_repo_dir.parent.parent.parent).as_posix()
    content = (
        f"---\n"
        f"type: repository-overview\n"
        f"repository: {repo_full_name}\n"
        f"branch: {branch}\n"
        f"file_count: {len(rel_paths)}\n"
        f"---\n\n"
        f"# {repo_full_name}\n\n"
        f"- Branch: `{branch}`\n"
        f"- Source files mirrored into `raw/repositories/`\n"
        f"- Wiki notes generated under `wiki/repositories/`\n"
        f"- Repo graph artifacts: `{graph_rel}`\n\n"
        f"## File Mix\n"
        + ("\n".join(f"- {item}" for item in ext_summary) if ext_summary else "- No supported files found")
        + "\n\n## Top-Level Areas\n"
        + ("\n".join(f"- {item}" for item in dir_summary) if dir_summary else "- No top-level directories found")
        + "\n\n## Source Notes\n"
        + (source_links if source_links else "- No source notes generated")
        + "\n"
    )

    overview_path = wiki_repo_dir / "overview.md"
    overview_path.write_text(content, encoding="utf-8")
    return overview_path


def build_document_page(
    title: str,
    original_filename: str,
    raw_rel_path: str,
    file_type: str,
    chunks: Sequence[ParsedChunk],
) -> str:
    sections: list[str] = []
    for index, chunk in enumerate(chunks[:20], start=1):
        excerpt = " ".join(chunk.content.split())
        excerpt = excerpt[:500].rstrip()
        if len(excerpt) == 500:
            excerpt += "..."
        heading = chunk.name or f"Section {index}"
        sections.append(f"### {index}. {heading}\n\n{excerpt}")

    sections_body = "\n\n".join(sections) if sections else "No parsed sections were produced."
    return (
        f"---\n"
        f"type: document-note\n"
        f"original_filename: {original_filename}\n"
        f"file_type: {file_type}\n"
        f"raw_path: {raw_rel_path}\n"
        f"chunk_count: {len(chunks)}\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"- Original file: `{original_filename}`\n"
        f"- File type: `{file_type}`\n"
        f"- Raw copy: `{raw_rel_path}`\n"
        f"- Parsed chunks: {len(chunks)}\n\n"
        f"## Extracted Sections\n\n"
        f"{sections_body}\n"
    )


def append_log_entry(vault_dir: Path, label: str, title: str, details: Iterable[str]) -> Path:
    ensure_vault_structure(vault_dir)
    log_path = vault_dir / "wiki" / "log.md"
    timestamp = datetime.now(timezone.utc)
    lines = [f"## [{timestamp.date().isoformat()}] ingest | {label} | {title}"]
    lines.extend(f"- {detail}" for detail in details)
    entry = "\n".join(lines).rstrip() + "\n\n"

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
    else:
        existing = "# Wiki Log\n\n"

    log_path.write_text(existing + entry, encoding="utf-8")
    return log_path


def rebuild_index(vault_dir: Path) -> Path:
    paths = ensure_vault_structure(vault_dir)
    wiki_root = paths["wiki_root"]

    repo_overviews = sorted(paths["wiki_repositories"].glob("*/overview.md"))
    document_pages = sorted(paths["wiki_documents"].glob("*.md"))

    excluded = {
        wiki_root / "index.md",
        wiki_root / "log.md",
    }
    other_pages = sorted(
        path for path in wiki_root.rglob("*.md")
        if path not in excluded
        and path not in repo_overviews
        and path not in document_pages
        and "sources" not in path.parts
        and "graphify-out" not in path.parts
    )

    def bullets(items: Sequence[Path]) -> str:
        if not items:
            return "- None yet"
        lines = []
        for item in items:
            rel = item.relative_to(wiki_root).as_posix()
            title = item.parent.name if item.name == "overview.md" else item.stem
            lines.append(f"- [{title}]({rel})")
        return "\n".join(lines)

    wiki_index = (
        "# Wiki Index\n\n"
        "## Repository Overviews\n"
        f"{bullets(repo_overviews)}\n\n"
        "## Documents\n"
        f"{bullets(document_pages)}\n\n"
        "## Other Pages\n"
        f"{bullets(other_pages)}\n\n"
        "## System Files\n"
        "- [log](log.md)\n"
    )
    (wiki_root / "index.md").write_text(wiki_index, encoding="utf-8")

    landing_index = (
        "# Knowledge Vault\n\n"
        "This vault is generated from repositories and uploaded documents using a raw-plus-wiki workflow.\n\n"
        "## Start Here\n"
        "- [Wiki index](wiki/index.md)\n"
        "- [Wiki log](wiki/log.md)\n"
        "- [Maintainer schema](AGENTS.md)\n"
        "- `raw/` stores immutable source copies\n"
        "- `graphs/` stores repository-level graph artifacts\n"
    )
    (vault_dir / "index.md").write_text(landing_index, encoding="utf-8")
    return wiki_root / "index.md"


def write_design_doc(repo_name: str, content: str) -> str:
    from app.core.config import get_settings
    vault_dir = resolve_vault_dir(get_settings().VAULT_PATH)
    # Store design.md alongside the repo wiki notes (consistent with vault structure)
    slug = repo_slug(repo_name)
    path = vault_dir / "wiki" / "repositories" / slug / "design.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)

