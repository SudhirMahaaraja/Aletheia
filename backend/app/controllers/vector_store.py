import logging
import numpy as np

from app.core.embeddings import embed_query

logger = logging.getLogger(__name__)


async def _embed_query(text: str, model_type: str = "text") -> list[float]:
    return await embed_query(text, model_type=model_type)


def _cosine_similarity_batch(query_vec: list[float], matrix: np.ndarray) -> np.ndarray:
    q = np.array(query_vec)
    norm_q = np.linalg.norm(q)
    if norm_q == 0:
        return np.zeros(matrix.shape[0])
    norms = np.linalg.norm(matrix, axis=1)
    norms = np.where(norms == 0, 1, norms)
    return (matrix @ q) / (norms * norm_q)


async def search_code(
    db,
    query: str,
    top_k: int = 10,
    repo_filter: list[str] | None = None,
) -> list[dict]:
    q_emb = await _embed_query(query, model_type="code")

    find_filter = {}
    if repo_filter:
        find_filter["repo_name"] = {"$in": repo_filter}

    cursor = db.code_chunks.find(find_filter, {
        "_id": 1,
        "name": 1,
        "chunk_type": 1,
        "content": 1,
        "language": 1,
        "file_path": 1,
        "repo_name": 1,
        "line_start": 1,
        "line_end": 1,
        "embedding": 1,
    })
    docs = await cursor.to_list(length=None)

    valid_docs = [d for d in docs if "embedding" in d and d["embedding"] is not None and len(d["embedding"]) == len(q_emb)]
    if not valid_docs:
        return []

    ids = [d["_id"] for d in valid_docs]
    matrix = np.array([d["embedding"] for d in valid_docs])
    scores = _cosine_similarity_batch(q_emb, matrix)

    results = []
    for i, score in enumerate(scores):
        if score >= 0.25:
            doc = valid_docs[i]
            doc.pop("embedding", None)
            results.append({
                "chunk_id": doc["_id"],
                "score": float(score),
                "collection": "code_chunks",
                "payload": {
                    "name": doc.get("name", ""),
                    "chunk_type": doc.get("chunk_type", ""),
                    "content": doc.get("content", ""),
                    "language": doc.get("language", ""),
                    "file_path": doc.get("file_path", ""),
                    "repo_name": doc.get("repo_name", ""),
                    "line_start": doc.get("line_start"),
                    "line_end": doc.get("line_end"),
                },
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


async def search_documents(
    db,
    query: str,
    top_k: int = 10,
) -> list[dict]:
    q_emb = await _embed_query(query, model_type="text")

    cursor = db.document_chunks.find({}, {
        "_id": 1,
        "document_id": 1,
        "document_title": 1,
        "section_heading": 1,
        "content": 1,
        "embedding": 1,
    })
    docs = await cursor.to_list(length=None)

    valid_docs = [d for d in docs if "embedding" in d and d["embedding"] is not None and len(d["embedding"]) == len(q_emb)]
    if not valid_docs:
        return []

    ids = [d["_id"] for d in valid_docs]
    matrix = np.array([d["embedding"] for d in valid_docs])
    scores = _cosine_similarity_batch(q_emb, matrix)

    results = []
    for i, score in enumerate(scores):
        if score >= 0.15:
            doc = valid_docs[i]
            doc.pop("embedding", None)
            results.append({
                "chunk_id": doc["_id"],
                "score": float(score),
                "collection": "document_chunks",
                "payload": {
                    "document_id": doc.get("document_id", ""),
                    "document_title": doc.get("document_title", ""),
                    "section_heading": doc.get("section_heading", ""),
                    "content": doc.get("content", ""),
                },
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


async def search_all(
    db,
    query: str,
    top_k: int = 10,
    repo_filter: list[str] | None = None,
) -> list[dict]:
    code_results = await search_code(db, query, top_k=top_k * 2, repo_filter=repo_filter)
    doc_results = await search_documents(db, query, top_k=top_k * 2)

    combined = code_results + doc_results
    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined[:top_k]
