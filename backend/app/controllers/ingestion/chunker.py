from typing import Optional

from app.controllers.ingestion.parsers.base_parser import BaseParser
from app.controllers.ingestion.parsers.js_parser import JSParser
from app.controllers.ingestion.parsers.python_parser import PythonParser
from app.controllers.ingestion.parsers.sql_parser import SQLParser

_python_parser = PythonParser()
_js_parser = JSParser()
_sql_parser = SQLParser()


class ChunkRouter:
    @staticmethod
    def get_parser(file_path: str) -> Optional[BaseParser]:
        lower = file_path.lower()
        if lower.endswith(".py"):
            return _python_parser
        if lower.endswith((".js", ".jsx", ".ts", ".tsx")):
            return _js_parser
        if lower.endswith(".sql"):
            return _sql_parser
        # .md and .txt are handled by DocumentParser separately
        return None
