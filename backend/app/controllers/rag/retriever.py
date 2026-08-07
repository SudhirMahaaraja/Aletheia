import logging
from typing import Optional
from app.controllers import vector_store
from app.controllers import graph_store

logger = logging.getLogger(__name__)


class HybridRetriever:
    @staticmethod
    async def retrieve(
        db,
        query: str,
        mode: str,  # "vault" | "repo" | "brainstorm"
        top_k: int = 5,
        repo_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Retrieves relevant chunks using vector search, then enriches them
        with relationship information from the knowledge graph.
        """
        # 1. Perform vector search based on the mode
        if mode == "vault":
            chunks = await vector_store.search_documents(db, query, top_k=top_k)
        elif mode == "repo":
            chunks = await vector_store.search_code(db, query, top_k=top_k, repo_filter=repo_filter)
        else:  # brainstorm
            chunks = await vector_store.search_all(db, query, top_k=top_k, repo_filter=repo_filter)

        enriched_chunks = []

        # 2. For each chunk, retrieve neighbors from graph store and format context
        for chunk in chunks:
            chunk_id = chunk["chunk_id"]
            collection = chunk["collection"]
            payload = chunk["payload"]
            score = chunk["score"]

            relationships = []
            try:
                # Get neighboring nodes
                neighbors = await graph_store.get_neighbors(db, chunk_id, depth=1)
                
                # Fetch outgoing/incoming edges for specific relationship types
                edges = await graph_store.get_edges_from(db, chunk_id)
                
                for edge in edges:
                    edge_type = edge["type"]
                    from_id = edge["from_id"]
                    to_id = edge["to_id"]
                    weight = edge.get("weight")

                    # Find the neighbor node details
                    neighbor_id = to_id if from_id == chunk_id else from_id
                    neighbor_node = next((n for n in neighbors if n["id"] == neighbor_id), None)
                    if not neighbor_node:
                        # If neighbor not in BFS, try fetching directly
                        neighbor_node = await graph_store.get_node(db, neighbor_id)

                    if neighbor_node:
                        name = neighbor_node.get("name", "")
                        ntype = neighbor_node.get("type", "")
                        summary = neighbor_node.get("summary", "")
                        
                        if from_id == chunk_id:
                            # Outgoing relationship
                            rel_str = f"-[{edge_type}]-> {ntype}: {name}"
                            if summary:
                                rel_str += f" ({summary})"
                        else:
                            # Incoming relationship
                            rel_str = f"<-[{edge_type}]- {ntype}: {name}"
                            if summary:
                                rel_str += f" ({summary})"
                        
                        if weight is not None:
                            rel_str += f" [similarity: {weight:.2f}]"
                        
                        relationships.append(rel_str)
            except Exception as e:
                logger.warning(f"Error enriching chunk {chunk_id} with graph neighbors: {e}")

            # Keep only unique relationship descriptions
            relationships = list(set(relationships))

            enriched_chunks.append({
                "chunk_id": chunk_id,
                "collection": collection,
                "payload": payload,
                "score": score,
                "relationships": relationships
            })

        return enriched_chunks
