import logging
import re

from app.controllers.ingestion.parsers.base_parser import BaseParser, ParsedChunk

logger = logging.getLogger(__name__)

# Try to use tree-sitter but fall back to regex if unavailable
_ts_available = False
_JS_LANGUAGE = None

try:
    import tree_sitter
    import tree_sitter_javascript as tsjs

    _JS_LANGUAGE = tree_sitter.Language(tsjs.language())
    _ts_available = True
    logger.info("tree-sitter JavaScript grammar loaded")
except Exception as exc:
    logger.warning("tree-sitter not available, JS parser will use regex fallback: %s", exc)


class JSParser(BaseParser):
    def parse(self, content: str, file_path: str) -> list[ParsedChunk]:
        from app.controllers.ingestion.parsers.base_parser import post_process_chunks
        if _ts_available:
            try:
                return post_process_chunks(self._parse_with_tree_sitter(content, file_path))
            except Exception as exc:
                logger.warning("tree-sitter parse failed for %s: %s -- falling back to regex", file_path, exc)

        try:
            return post_process_chunks(self._parse_with_regex(content, file_path))
        except Exception as exc:
            logger.error("regex parse failed for %s: %s -- falling back to line-window chunks", file_path, exc)
            from app.core.config import get_settings
            from app.controllers.ingestion.parsers.base_parser import chunk_oversized_content
            max_chars = get_settings().MAX_EMBEDDING_CHARS
            content_chunks = chunk_oversized_content(content, max_chars)
            fallback_chunks = []
            current_line = 1
            for idx, chunk_content in enumerate(content_chunks):
                chunk_lines = chunk_content.count("\n") + 1
                fallback_chunks.append(ParsedChunk(
                    chunk_type="file",
                    name=f"{file_path.split('/')[-1]}_part_{idx + 1}" if len(content_chunks) > 1 else file_path.split("/")[-1],
                    content=chunk_content,
                    language=self._detect_language(file_path),
                    file_path=file_path,
                    line_start=current_line,
                    line_end=current_line + chunk_lines - 1,
                    imports=[],
                    calls=[],
                    metadata={"part": idx + 1} if len(content_chunks) > 1 else {},
                ))
                current_line += chunk_lines
            return post_process_chunks(fallback_chunks)

    def _parse_with_tree_sitter(self, content: str, file_path: str) -> list[ParsedChunk]:
        import tree_sitter

        parser = tree_sitter.Parser(_JS_LANGUAGE)
        source_bytes = content.encode("utf-8")
        tree = parser.parse(source_bytes)
        root = tree.root_node

        chunks: list[ParsedChunk] = []
        lines = content.splitlines()
        
        imports = []
        stack = [root]
        
        while stack:
            node = stack.pop()
            
            if node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                if source_node:
                    path = self._ts_text(source_node, source_bytes).strip("'\"")
                    imports.append(path)
            
            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                name = self._ts_text(name_node, source_bytes) if name_node else "anonymous"
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                body_text = self._ts_text(node, source_bytes)
                calls = self._ts_extract_calls(node, source_bytes)
                
                chunks.append(ParsedChunk(
                    chunk_type="function",
                    name=name,
                    content=body_text,
                    language=self._detect_language(file_path),
                    file_path=file_path,
                    line_start=start_line,
                    line_end=end_line,
                    imports=[],
                    calls=calls,
                ))
            
            elif node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                name = self._ts_text(name_node, source_bytes) if name_node else "AnonymousClass"
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                body_text = self._ts_text(node, source_bytes)
                calls = self._ts_extract_calls(node, source_bytes)
                
                chunks.append(ParsedChunk(
                    chunk_type="class",
                    name=name,
                    content=body_text,
                    language=self._detect_language(file_path),
                    file_path=file_path,
                    line_start=start_line,
                    line_end=end_line,
                    imports=[],
                    calls=calls,
                ))
            
            elif node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                if value and value.type == "arrow_function":
                    name_node = node.child_by_field_name("name")
                    name = self._ts_text(name_node, source_bytes) if name_node else "anonymous"
                    
                    parent = node.parent
                    while parent and parent.type not in ("lexical_declaration", "variable_declaration"):
                        parent = parent.parent
                    
                    start_line = (parent or node).start_point[0] + 1
                    end_line = (parent or node).end_point[0] + 1
                    body_text = self._ts_text(parent or node, source_bytes)
                    calls = self._ts_extract_calls(value, source_bytes)
                    
                    chunks.append(ParsedChunk(
                        chunk_type="function",
                        name=name,
                        content=body_text,
                        language=self._detect_language(file_path),
                        file_path=file_path,
                        line_start=start_line,
                        line_end=end_line,
                        imports=[],
                        calls=calls,
                    ))

            for child in reversed(node.children):
                stack.append(child)
        
        imports = list(set(imports))
        for chunk in chunks:
            chunk.imports = imports

        chunks.append(ParsedChunk(
            chunk_type="file",
            name=file_path.split("/")[-1],
            content=content,
            language=self._detect_language(file_path),
            file_path=file_path,
            line_start=1,
            line_end=len(lines),
            imports=imports,
            calls=[],
        ))

        return chunks


    def _ts_find_nodes(self, node, types: list[str]) -> list:
        results = []
        stack = [node]
        while stack:
            curr = stack.pop()
            if curr.type in types:
                results.append(curr)
            for child in reversed(curr.children):
                stack.append(child)
        return results


    def _ts_text(self, node, source_bytes: bytes) -> str:
        if node is None:
            return ""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _ts_extract_imports(self, root, source_bytes: bytes) -> list[str]:
        imports = []
        for node in self._ts_find_nodes(root, ["import_statement"]):
            source_node = node.child_by_field_name("source")
            if source_node:
                path = self._ts_text(source_node, source_bytes).strip("'\"")
                imports.append(path)
        return list(set(imports))

    def _ts_extract_calls(self, node, source_bytes: bytes) -> list[str]:
        calls = []
        for call_node in self._ts_find_nodes(node, ["call_expression"]):
            func_node = call_node.child_by_field_name("function")
            if func_node:
                if func_node.type == "identifier":
                    calls.append(self._ts_text(func_node, source_bytes))
                elif func_node.type == "member_expression":
                    prop = func_node.child_by_field_name("property")
                    if prop:
                        calls.append(self._ts_text(prop, source_bytes))
        return list(set(calls))

    def _parse_with_regex(self, content: str, file_path: str) -> list[ParsedChunk]:
        lines = content.splitlines()
        chunks: list[ParsedChunk] = []
        language = self._detect_language(file_path)

        # Extract imports
        import_patterns = [
            re.compile(r'import\s+.*?\s+from\s+[\'"](.+?)[\'"]'),
            re.compile(r'import\s+[\'"](.+?)[\'"]'),
            re.compile(r'require\s*\(\s*[\'"](.+?)[\'"]\s*\)'),
        ]
        imports = []
        for pattern in import_patterns:
            for match in pattern.finditer(content):
                imports.append(match.group(1))
        imports = list(set(imports))

        # Extract functions
        func_pattern = re.compile(
            r'(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)',
        )
        for match in func_pattern.finditer(content):
            name = match.group(1)
            start_pos = match.start()
            start_line = content[:start_pos].count("\n") + 1
            chunks.append(ParsedChunk(
                chunk_type="function",
                name=name,
                content=content[start_pos:],
                language=language,
                file_path=file_path,
                line_start=start_line,
                line_end=None,
                imports=imports,
                calls=[],
            ))

        # Extract arrow functions
        arrow_pattern = re.compile(
            r'(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:\(.*?\)|[a-zA-Z0-9_$]+)\s*=>',
        )
        for match in arrow_pattern.finditer(content):
            name = match.group(1)
            start_pos = match.start()
            start_line = content[:start_pos].count("\n") + 1
            chunks.append(ParsedChunk(
                chunk_type="function",
                name=name,
                content=content[start_pos:],
                language=language,
                file_path=file_path,
                line_start=start_line,
                line_end=None,
                imports=imports,
                calls=[],
            ))

        # Extract classes
        class_pattern = re.compile(r'(?:export\s+)?class\s+([a-zA-Z0-9_$]+)')
        for match in class_pattern.finditer(content):
            name = match.group(1)
            start_pos = match.start()
            start_line = content[:start_pos].count("\n") + 1
            chunks.append(ParsedChunk(
                chunk_type="class",
                name=name,
                content=content[start_pos:],
                language=language,
                file_path=file_path,
                line_start=start_line,
                line_end=None,
                imports=imports,
                calls=[],
            ))

        # Always add a file-level chunk representing the whole file
        chunks.append(ParsedChunk(
            chunk_type="file",
            name=file_path.split("/")[-1],
            content=content,
            language=language,
            file_path=file_path,
            line_start=1,
            line_end=len(lines),
            imports=imports,
            calls=[],
        ))

        return chunks

    def _detect_language(self, file_path: str) -> str:
        lower = file_path.lower()
        if lower.endswith((".ts", ".tsx")):
            return "typescript"
        if lower.endswith(".jsx"):
            return "jsx"
        return "javascript"
