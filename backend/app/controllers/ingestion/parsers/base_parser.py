from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParsedChunk:
    chunk_type: str       # "function" | "class" | "file" | "sql_statement" | "section"
    name: str
    content: str
    language: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class BaseParser(ABC):
    @abstractmethod
    def parse(self, content: str, file_path: str) -> list[ParsedChunk]:
        ...


def split_chunk_by_lines(chunk: ParsedChunk, max_chars: int = 4000) -> list[ParsedChunk]:
    if len(chunk.content) <= max_chars:
        return [chunk]

    chunks = []
    current_chunk_lines = []
    current_len = 0
    part_idx = 1
    
    orig_start = chunk.line_start if chunk.line_start is not None else 1
    current_start = orig_start

    for line in chunk.content.splitlines():
        if current_len + len(line) + 1 > max_chars:
            if current_chunk_lines:
                chunk_content = "\n".join(current_chunk_lines)
                end_line = current_start + len(current_chunk_lines) - 1
                chunks.append(ParsedChunk(
                    chunk_type=chunk.chunk_type,
                    name=f"{chunk.name}_part_{part_idx}",
                    content=chunk_content,
                    language=chunk.language,
                    file_path=chunk.file_path,
                    line_start=current_start,
                    line_end=end_line,
                    imports=chunk.imports,
                    calls=chunk.calls,
                    metadata={**chunk.metadata, "part": part_idx},
                ))
                part_idx += 1
                current_start = end_line + 1
            current_chunk_lines = [line]
            current_len = len(line) + 1
        else:
            current_chunk_lines.append(line)
            current_len += len(line) + 1

    if current_chunk_lines:
        chunk_content = "\n".join(current_chunk_lines)
        end_line = current_start + len(current_chunk_lines) - 1
        chunks.append(ParsedChunk(
            chunk_type=chunk.chunk_type,
            name=f"{chunk.name}_part_{part_idx}" if part_idx > 1 else chunk.name,
            content=chunk_content,
            language=chunk.language,
            file_path=chunk.file_path,
            line_start=current_start,
            line_end=end_line,
            imports=chunk.imports,
            calls=chunk.calls,
            metadata={**chunk.metadata, "part": part_idx} if part_idx > 1 else chunk.metadata,
        ))

    return chunks


def chunk_oversized_content(content: str, max_chars: int = 2000) -> list[str]:
    lines = content.split("\n")
    chunks, current, current_len = [], [], 0
    for line in lines:
        if current_len + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def post_process_chunks(chunks: list[ParsedChunk], max_chars: int | None = None) -> list[ParsedChunk]:
    if max_chars is None:
        try:
            from app.core.config import get_settings
            max_chars = get_settings().MAX_EMBEDDING_CHARS
        except Exception:
            max_chars = 2000
    processed = []
    for chunk in chunks:
        processed.extend(split_chunk_by_lines(chunk, max_chars))
    return processed


def detect_language(file_path: str) -> str:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    ext_map = {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "html": "html",
        "css": "css",
        "java": "java",
        "cpp": "cpp",
        "c": "c",
        "h": "c",
        "go": "go",
        "sh": "shell",
        "sql": "sql",
        "md": "markdown",
        "txt": "text",
        "json": "json",
    }
    return ext_map.get(ext, "text")


