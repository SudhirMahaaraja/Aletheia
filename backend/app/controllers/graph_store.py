import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def get_node(db, node_id: str) -> Optional[dict]:
    doc = await db.graph_nodes.find_one({"_id": node_id})
    if not doc:
        return None
    doc["id"] = doc.pop("_id")
    return doc


async def get_neighbors(db, node_id: str, depth: int = 1) -> list[dict]:
    visited = set()
    frontier = [node_id]
    neighbors = []

    for _ in range(depth):
        next_frontier = []
        for nid in frontier:
            if nid in visited:
                continue
            visited.add(nid)

            # Outgoing edges
            cursor = db.graph_edges.find({"from_id": nid})
            edges = await cursor.to_list(length=200)
            for edge in edges:
                target_id = edge["to_id"]
                if target_id not in visited:
                    node = await db.graph_nodes.find_one({"_id": target_id})
                    if node:
                        node["id"] = node.pop("_id")
                        neighbors.append(node)
                        next_frontier.append(target_id)

            # Incoming edges
            cursor = db.graph_edges.find({"to_id": nid})
            edges = await cursor.to_list(length=200)
            for edge in edges:
                source_id = edge["from_id"]
                if source_id not in visited:
                    node = await db.graph_nodes.find_one({"_id": source_id})
                    if node:
                        node["id"] = node.pop("_id")
                        neighbors.append(node)
                        next_frontier.append(source_id)

        frontier = next_frontier

    return neighbors


async def get_edges_from(db, node_id: str) -> list[dict]:
    cursor = db.graph_edges.find({
        "$or": [{"from_id": node_id}, {"to_id": node_id}],
    })
    edges = await cursor.to_list(length=500)
    result = []
    for edge in edges:
        edge["id"] = str(edge.pop("_id"))
        result.append(edge)
    return result


async def get_nodes_by_type(db, node_type: str, limit: int = 100) -> list[dict]:
    cursor = db.graph_nodes.find({"type": node_type}).limit(limit)
    nodes = await cursor.to_list(length=limit)
    result = []
    for node in nodes:
        node["id"] = node.pop("_id")
        result.append(node)
    return result


async def get_all_nodes(db, skip: int = 0, limit: int = 500) -> list[dict]:
    cursor = db.graph_nodes.find({}).skip(skip).limit(limit)
    nodes = await cursor.to_list(length=limit)
    result = []
    for node in nodes:
        node["id"] = node.pop("_id")
        result.append(node)
    return result


async def get_all_edges(db, skip: int = 0, limit: int = 1000) -> list[dict]:
    cursor = db.graph_edges.find({}).skip(skip).limit(limit)
    edges = await cursor.to_list(length=limit)
    result = []
    for edge in edges:
        edge["id"] = str(edge.pop("_id"))
        result.append(edge)
    return result


async def find_nodes_by_name(db, search: str, limit: int = 20) -> list[dict]:
    cursor = db.graph_nodes.find(
        {"$text": {"$search": search}},
        {"score": {"$meta": "textScore"}},
    ).sort(
        [("score", {"$meta": "textScore"})]
    ).limit(limit)
    nodes = await cursor.to_list(length=limit)
    result = []
    for node in nodes:
        node["id"] = node.pop("_id")
        result.append(node)
    return result
