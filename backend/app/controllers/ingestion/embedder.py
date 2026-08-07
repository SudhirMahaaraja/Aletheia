import hashlib
import json
import logging
from datetime import datetime, timezone

from pymongo import UpdateOne

from app.core.config import get_settings
from app.controllers.ingestion.parsers.base_parser import ParsedChunk

from app.core.embeddings import embed_texts

logger = logging.getLogger(__name__)


def _make_chunk_id(
    chunk: ParsedChunk,
    collection: str,
    repo_name: str | None = None,
    document_id: str | None = None,
) -> str:
    metadata_blob = json.dumps(chunk.metadata or {}, sort_keys=True, default=str)
    raw = "|".join([
        collection,
        repo_name or "",
        document_id or "",
        chunk.file_path or "",
        chunk.name or "",
        chunk.chunk_type or "",
        chunk.language or "",
        str(chunk.line_start or ""),
        str(chunk.line_end or ""),
        metadata_blob,
        hashlib.sha256(chunk.content.encode("utf-8", errors="ignore")).hexdigest()[:16],
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def embed_chunks(
    chunks: list[ParsedChunk],
    collection: str,
    db,
    repo_name: str | None = None,
    document_id: str | None = None,
    document_title: str | None = None,
) -> list[str]:
    settings = get_settings()
    batch_size = settings.EMBEDDING_BATCH_SIZE
    chunk_ids: list[str] = []
    now = datetime.now(timezone.utc)

    total_batches = (len(chunks) + batch_size - 1) // batch_size

    for batch_idx in range(0, len(chunks), batch_size):
        batch = chunks[batch_idx : batch_idx + batch_size]
        batch_num = batch_idx // batch_size + 1
        texts = [c.content[:settings.MAX_EMBEDDING_CHARS] for c in batch]  # truncate to model's max context

        try:
            model_type = "code" if collection == "code_chunks" else "text"
            embeddings_list = await embed_texts(texts, model_type=model_type)
        except Exception as exc:
            logger.error("Local Jina embedding failed for batch %d/%d: %s", batch_num, total_batches, exc)
            raise

        operations = []
        for i, chunk in enumerate(batch):
            chunk_id = _make_chunk_id(
                chunk,
                collection=collection,
                repo_name=repo_name,
                document_id=document_id,
            )
            chunk_ids.append(chunk_id)
            embedding = embeddings_list[i]

            if collection == "code_chunks":
                doc = {
                    "_id": chunk_id,
                    "chunk_type": chunk.chunk_type,
                    "name": chunk.name,
                    "content": chunk.content,
                    "language": chunk.language,
                    "file_path": chunk.file_path,
                    "repo_name": repo_name or "",
                    "project_id": None,
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                    "embedding": embedding,
                    "created_at": now,
                    "updated_at": now,
                }
            else:  # document_chunks
                doc = {
                    "_id": chunk_id,
                    "document_id": document_id or "",
                    "document_title": document_title or "",
                    "file_type": chunk.metadata.get("file_type", ""),
                    "page_number": chunk.metadata.get("page_number"),
                    "section_heading": chunk.metadata.get("heading"),
                    "content": chunk.content,
                    "embedding": embedding,
                    "created_at": now,
                    "updated_at": now,
                }

            operations.append(
                UpdateOne(
                    {"_id": chunk_id},
                    {"$set": doc},
                    upsert=True,
                )
            )

        if operations:
            try:
                coll = db[collection]
                await coll.bulk_write(operations, ordered=False)
            except Exception as exc:
                logger.error("Bulk write failed for batch %d/%d: %s", batch_num, total_batches, exc)
                raise

        logger.info("Embedded batch %d/%d -> %s", batch_num, total_batches, collection)

        pass

    return chunk_ids
