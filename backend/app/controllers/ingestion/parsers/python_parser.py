import ast
import logging
import textwrap

from app.controllers.ingestion.parsers.base_parser import BaseParser, ParsedChunk

logger = logging.getLogger(__name__)


class PythonParser(BaseParser):
    def parse(self, content: str, file_path: str) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        lines = content.splitlines()

        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError as exc:
            logger.warning("SyntaxError parsing %s: %s -- falling back to line-window chunks", file_path, exc)
            from app.core.config import get_settings
            from app.controllers.ingestion.parsers.base_parser import chunk_oversized_content, post_process_chunks
            max_chars = get_settings().MAX_EMBEDDING_CHARS
            content_chunks = chunk_oversized_content(content, max_chars)
            fallback_chunks = []
            current_line = 1
            all_imports = self._extract_imports_raw(content)
            for idx, chunk_content in enumerate(content_chunks):
                chunk_lines = chunk_content.count("\n") + 1
                fallback_chunks.append(ParsedChunk(
                    chunk_type="file",
                    name=f"{file_path.split('/')[-1]}_part_{idx + 1}" if len(content_chunks) > 1 else file_path.split("/")[-1],
                    content=chunk_content,
                    language="python",
                    file_path=file_path,
                    line_start=current_line,
                    line_end=current_line + chunk_lines - 1,
                    imports=all_imports,
                    calls=[],
                    metadata={"part": idx + 1} if len(content_chunks) > 1 else {},
                ))
                current_line += chunk_lines
            return post_process_chunks(fallback_chunks)

        # Extract module-level imports
        module_imports = self._extract_imports(tree)

        # Process top-level nodes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunk = self._extract_function(node, lines, file_path, module_imports)
                chunks.append(chunk)
            elif isinstance(node, ast.ClassDef):
                chunk = self._extract_class(node, lines, file_path, module_imports)
                chunks.append(chunk)

        # Always add a file-level chunk representing the whole file,
        # so we don't lose any content outside functions and classes.
        chunks.append(ParsedChunk(
            chunk_type="file",
            name=file_path.split("/")[-1],
            content=content,
            language="python",
            file_path=file_path,
            line_start=1,
            line_end=len(lines),
            imports=module_imports,
            calls=self._extract_all_calls(tree),
            metadata={},
        ))

        from app.controllers.ingestion.parsers.base_parser import post_process_chunks
        return post_process_chunks(chunks)

    def _extract_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        lines: list[str],
        file_path: str,
        module_imports: list[str],
    ) -> ParsedChunk:
        start = node.lineno
        end = node.end_lineno or node.lineno
        source = "\n".join(lines[start - 1 : end])

        calls = self._extract_calls_from_node(node)

        return ParsedChunk(
            chunk_type="function",
            name=node.name,
            content=source,
            language="python",
            file_path=file_path,
            line_start=start,
            line_end=end,
            imports=module_imports,
            calls=calls,
            metadata={"is_async": isinstance(node, ast.AsyncFunctionDef)},
        )

    def _extract_class(
        self,
        node: ast.ClassDef,
        lines: list[str],
        file_path: str,
        module_imports: list[str],
    ) -> ParsedChunk:
        start = node.lineno
        end = node.end_lineno or node.lineno
        source = "\n".join(lines[start - 1 : end])

        calls = self._extract_calls_from_node(node)

        return ParsedChunk(
            chunk_type="class",
            name=node.name,
            content=source,
            language="python",
            file_path=file_path,
            line_start=start,
            line_end=end,
            imports=module_imports,
            calls=calls,
            metadata={"bases": [self._get_name(b) for b in node.bases]},
        )

    def _extract_imports(self, tree: ast.Module) -> list[str]:
        imports: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                dots = "." * node.level
                for alias in node.names:
                    if module:
                        imports.append(f"{dots}{module}.{alias.name}")
                    else:
                        imports.append(f"{dots}{alias.name}")
        return list(set(imports))

    def _extract_imports_raw(self, content: str) -> list[str]:
        imports: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports

    def _extract_calls_from_node(self, node: ast.AST) -> list[str]:
        calls: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = self._get_call_name(child)
                if name:
                    calls.append(name)
        return list(set(calls))

    def _extract_all_calls(self, tree: ast.Module) -> list[str]:
        return self._extract_calls_from_node(tree)

    def _get_call_name(self, node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        elif isinstance(func, ast.Attribute):
            return func.attr
        return ""

    def _get_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return ""
