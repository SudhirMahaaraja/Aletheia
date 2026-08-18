from typing import Optional

from pydantic import BaseModel


class GraphNodeResponse(BaseModel):
    id: str
    type: str
    name: str
    repo_name: Optional[str] = None
    file_path: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    metadata: dict = {}


class GraphEdgeResponse(BaseModel):
    id: str
    from_id: str
    to_id: str
    type: str
    weight: Optional[float] = None


class NodeDetailResponse(BaseModel):
    node: GraphNodeResponse
    neighbors: list[GraphNodeResponse] = []
    edges: list[GraphEdgeResponse] = []
