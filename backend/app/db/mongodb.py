import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MongoDBClient:
    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        settings = get_settings()
        logger.info("Connecting to MongoDB at %s ...", settings.MONGO_URI)
        self._client = AsyncIOMotorClient(settings.MONGO_URI)
        self._db = self._client[settings.MONGO_DB_NAME]
        try:
            await self._client.admin.command("ping")
            logger.info("MongoDB connection verified (ping OK), database: %s", settings.MONGO_DB_NAME)
        except Exception as exc:
            logger.error("MongoDB ping failed: %s", exc)
            raise
        await self._create_indexes()

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            logger.info("MongoDB connection closed")

    def get_db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def _create_indexes(self) -> None:
        db = self.get_db()
        logger.info("Creating MongoDB indexes ...")

        # ---- users ----
        await db.users.create_index([("email", ASCENDING)], unique=True)

        # ---- refresh_tokens ----
        await db.refresh_tokens.create_index([("user_id", ASCENDING)])
        await db.refresh_tokens.create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
        )

        # ---- projects ----
        await db.projects.create_index([("name", ASCENDING)], unique=True)

        # ---- repositories ----
        await db.repositories.create_index([("github_full_name", ASCENDING)], unique=True)

        # ---- documents ----
        await db.documents.create_index([("uploaded_by", ASCENDING)])

        # ---- ingestion_jobs ----
        await db.ingestion_jobs.create_index([("status", ASCENDING)])
        await db.ingestion_jobs.create_index([("source_id", ASCENDING)])

        # ---- chat_sessions ----
        await db.chat_sessions.create_index([("user_id", ASCENDING)])

        # ---- chat_messages ----
        await db.chat_messages.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])

        # ---- graph_nodes ----
        await db.graph_nodes.create_index([("type", ASCENDING)])
        await db.graph_nodes.create_index([("repo_name", ASCENDING)])
        # Drop old text index if it exists (may have wrong language_override)
        try:
            await db.graph_nodes.drop_index("graph_nodes_text_idx")
        except Exception:
            pass  # index may not exist yet
        await db.graph_nodes.create_index(
            [("name", TEXT), ("summary", TEXT)],
            name="graph_nodes_text_idx",
            default_language="english",
            language_override="none",
        )

        # ---- graph_edges ----
        await db.graph_edges.create_index([("from_id", ASCENDING)])
        await db.graph_edges.create_index([("to_id", ASCENDING)])
        await db.graph_edges.create_index([("from_id", ASCENDING), ("type", ASCENDING)])

        # ---- audit_logs ----
        await db.audit_logs.create_index([("user_id", ASCENDING)])
        await db.audit_logs.create_index([("created_at", DESCENDING)])
        await db.audit_logs.create_index(
            [("created_at", ASCENDING)],
            expireAfterSeconds=90 * 24 * 60 * 60,  # 90 days TTL
            name="audit_logs_ttl",
        )

        # ---- code_chunks (vector storage) ----
        # schema: "embedding": list[float]   # 768-dimensional vector (jina-embeddings-v2-base-code)
        await db.code_chunks.create_index([("repo_name", ASCENDING)])
        await db.code_chunks.create_index([("chunk_type", ASCENDING)])

        # ---- document_chunks (vector storage) ----
        # schema: "embedding": list[float]   # 768-dimensional vector (jina-embeddings-v2-base-code)
        await db.document_chunks.create_index([("document_id", ASCENDING)])

        logger.info("All MongoDB indexes created successfully")


# Module-level singleton
mongodb_client = MongoDBClient()


async def get_db() -> AsyncIOMotorDatabase:
    return mongodb_client.get_db()
