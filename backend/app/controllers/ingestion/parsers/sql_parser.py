import logging

import sqlparse

from app.controllers.ingestion.parsers.base_parser import BaseParser, ParsedChunk

logger = logging.getLogger(__name__)


class SQLParser(BaseParser):
    def parse(self, content: str, file_path: str) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []

        try:
            statements = sqlparse.split(content)
        except Exception as exc:
            logger.warning("sqlparse failed for %s: %s -- falling back to file-level chunk", file_path, exc)
            from app.controllers.ingestion.parsers.base_parser import post_process_chunks
            return post_process_chunks([ParsedChunk(
                chunk_type="file",
                name=file_path.split("/")[-1],
                content=content,
                language="sql",
                file_path=file_path,
                line_start=1,
                line_end=len(content.splitlines()),
                imports=[],
                calls=[],
            )])

        for idx, stmt in enumerate(statements):
            stmt = stmt.strip()
            if not stmt:
                continue

            # Detect statement type
            try:
                parsed = sqlparse.parse(stmt)
                stmt_type = parsed[0].get_type() if parsed else "UNKNOWN"
            except Exception:
                stmt_type = "UNKNOWN"

            if stmt_type is None:
                stmt_type = "UNKNOWN"

            name = f"{stmt_type}_{idx}"

            # Calculate approximate line positions
            preceding = "\n".join(statements[:idx])
            start_line = preceding.count("\n") + 1 if preceding else 1
            end_line = start_line + stmt.count("\n")

            chunks.append(ParsedChunk(
                chunk_type="sql_statement",
                name=name,
                content=stmt,
                language="sql",
                file_path=file_path,
                line_start=start_line,
                line_end=end_line,
                imports=[],
                calls=[],
                metadata={"statement_type": stmt_type},
            ))

        if not chunks:
            chunks.append(ParsedChunk(
                chunk_type="file",
                name=file_path.split("/")[-1],
                content=content,
                language="sql",
                file_path=file_path,
                line_start=1,
                line_end=len(content.splitlines()),
                imports=[],
                calls=[],
            ))

        from app.controllers.ingestion.parsers.base_parser import post_process_chunks
        return post_process_chunks(chunks)
