import logging
import json
from datetime import datetime, timezone
import openai
from bson import ObjectId

from app.core.config import get_settings
from app.controllers.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)


def _get_openai_client():
    settings = get_settings()
    if settings.OPENAI_ENDPOINT and "azure" in settings.OPENAI_ENDPOINT.lower():
        return openai.AsyncAzureOpenAI(
            api_key=settings.OPENAI_API_KEY,
            azure_endpoint=settings.OPENAI_ENDPOINT,
            api_version=settings.OPENAI_API_VERSION or "2024-08-01-preview",
        )
    return openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


class RepoChatService:
    @staticmethod
    async def stream_response(
        db,
        session_id: str,
        user_id: str,
        question: str,
        chat_history: list,
        selected_repos: list[str] | None = None,
        ip_address: str = "",
    ):
        """
        Streams a RAG response for Repo Chat (suggesting code reuse and module reuse from existing repositories).
        Yields SSE formatted data events.
        """
        settings = get_settings()
        client = _get_openai_client()
        now = datetime.now(timezone.utc)

        # 1. Fetch current session context summary
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        is_admin = user and user.get("role") in ("admin", "superadmin")

        query = {"_id": session_id}
        if not is_admin:
            query["user_id"] = user_id

        session_doc = await db.chat_sessions.find_one(query)
        if not session_doc and ObjectId.is_valid(session_id):
            query_oid = {"_id": ObjectId(session_id)}
            if not is_admin:
                query_oid["user_id"] = user_id
            session_doc = await db.chat_sessions.find_one(query_oid)

        context_summary = ""
        if session_doc:
            context_summary = session_doc.get("context_summary", "")
            # Merge session-level selected repos if not explicitly passed
            if not selected_repos:
                selected_repos = session_doc.get("selected_repos", [])

        # 2. Reformulate the query if there is history
        rewritten_query = question
        if chat_history and settings.OPENAI_API_KEY:
            reformulation_prompt = (
                "Given the following conversation summary, recent turn history, and a follow-up question, "
                "rephrase the follow-up question to be a standalone search query that captures all necessary context, "
                "specifically targeting programming languages, functions, classes, file names, or architectural patterns discussed.\n"
                "Output ONLY the standalone rephrased search query. Do not add any explanation, quotes, or preamble.\n\n"
            )
            if context_summary:
                reformulation_prompt += f"Conversation Summary Context:\n{context_summary}\n\n"

            reformulation_prompt += "Recent History:\n"
            for msg in chat_history[-4:]:
                role_label = "User" if msg["role"] == "user" else "Assistant"
                reformulation_prompt += f"{role_label}: {msg['content']}\n"
            
            reformulation_prompt += f"Follow-up Question: {question}\n"
            reformulation_prompt += "Standalone Question:"

            try:
                resp = await client.chat.completions.create(
                    model=settings.OPENAI_CHAT_MODEL,
                    messages=[{"role": "user", "content": reformulation_prompt}],
                    temperature=0.0,
                )
                rewritten_query = resp.choices[0].message.content.strip()
                if rewritten_query.startswith('"') and rewritten_query.endswith('"'):
                    rewritten_query = rewritten_query[1:-1].strip()
            except Exception as e:
                logger.warning(f"Query reformulation failed: {e}")

        # 3. Retrieve code chunks using HybridRetriever
        enriched_chunks = await HybridRetriever.retrieve(
            db=db,
            query=rewritten_query,
            mode="repo",
            top_k=5,
            repo_filter=selected_repos,
        )

        context_str = ""
        sources = []
        for chunk in enriched_chunks:
            payload = chunk["payload"]
            name = payload.get("name", "Unnamed Chunk")
            ctype = payload.get("chunk_type", "file")
            file_path = payload.get("file_path", "")
            repo_name = payload.get("repo_name", "")
            content = payload.get("content", "")
            lang = payload.get("language", "")
            start = payload.get("line_start", 1)
            end = payload.get("line_end", 1)
            score = chunk["score"]

            source_info = f"Repository: {repo_name} | File: {file_path} | Type: {ctype} | Name: {name} | Lines: {start}-{end} | Similarity: {score:.2f}"
            context_str += f"[{source_info}]\n"
            context_str += f"```{lang}\n{content}\n```\n"
            
            # Enrich relationships if any
            if chunk["relationships"]:
                context_str += "Graph Relationships & Dependencies:\n"
                for rel in chunk["relationships"]:
                    context_str += f"- {rel}\n"
            context_str += "---\n\n"

            sources.append({
                "repo_name": repo_name,
                "file_path": file_path,
                "name": name,
                "chunk_type": ctype,
                "chunk_id": str(chunk["chunk_id"]) if chunk.get("chunk_id") is not None else ""
            })

        # Deduplicate sources
        unique_sources = []
        seen_chunks = set()
        for src in sources:
            cid = src["chunk_id"]
            if cid not in seen_chunks:
                seen_chunks.add(cid)
                unique_sources.append(src)

        # 4. Construct prompt for GPT-4o
        system_prompt = (
            "You are the BWS Second Brain codebase assistant. Your primary purpose is to help developers discover and reuse existing code and modules.\n"
            "Analyze the retrieved code context and suggest exact reuse recommendations. For any matches:\n"
            "1. Output a structured match report detailing which function, class, or module can be reused, its path/repo, and how to adapt it.\n"
            "2. Extract and output the complete, exact code snippet from the context rather than rewriting or generating mock placeholder code.\n"
            "3. If dependencies or import structures are available in the context relationships, describe them so the developer knows how to link this module.\n"
            "Explain specifically why this code meets the user's request and how it can save them time."
        )

        if context_summary:
            system_prompt += f"\n\nHere is a summary of the conversation history for context:\n{context_summary}"

        messages = [
            {"role": "system", "content": f"{system_prompt}\n\nCode Context:\n{context_str or 'No relevant code matches found.'}"}
        ]

        # Append last 4 messages of history
        for msg in chat_history[-4:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": question})

        full_answer = ""
        try:
            if not settings.OPENAI_API_KEY:
                fallback = (
                    "OpenAI API key is missing. However, here is the relevant code context matching your question:\n\n"
                    f"{context_str or 'No matching code chunks found.'}"
                )
                yield f"data: {json.dumps({'token': fallback})}\n\n"
                full_answer = fallback
            else:
                stream = await client.chat.completions.create(
                    model=settings.OPENAI_CHAT_MODEL,
                    messages=messages,
                    temperature=0.1,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        token = delta.content
                        full_answer += token
                        yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as e:
            error_msg = f"Error generating answer from OpenAI LLM: {str(e)}"
            yield f"data: {json.dumps({'token': error_msg})}\n\n"
            full_answer = error_msg

        # Resolve node_id for each source
        for src in unique_sources:
            node_id = None
            repo_name = src.get("repo_name", "")
            file_path = src.get("file_path", "")
            name = src.get("name", "")
            
            node = await db.graph_nodes.find_one({
                "repo_name": repo_name,
                "file_path": file_path,
                "name": name
            })
            if node:
                node_id = str(node["_id"])
            else:
                node = await db.graph_nodes.find_one({
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "type": "File"
                })
                if node:
                    node_id = str(node["_id"])
                else:
                    node = await db.graph_nodes.find_one({
                        "repo_name": repo_name,
                        "type": "Repository"
                    })
                    if node:
                        node_id = str(node["_id"])
            src["node_id"] = node_id

        # Send done event with sources
        yield f"data: {json.dumps({'done': True, 'sources': unique_sources})}\n\n"

        # 5. Save user and assistant messages to database
        user_msg_doc = {
            "session_id": session_id,
            "role": "user",
            "content": question,
            "sources": [],
            "created_at": now,
        }
        assistant_msg_doc = {
            "session_id": session_id,
            "role": "assistant",
            "content": full_answer,
            "sources": unique_sources,
            "created_at": datetime.now(timezone.utc),
        }

        try:
            await db.chat_messages.insert_one(user_msg_doc)
            await db.chat_messages.insert_one(assistant_msg_doc)
        except Exception as e:
            logger.error(f"Failed to insert chat messages: {e}")

        # 6. Update message count and handle rolling summary
        msg_count = await db.chat_messages.count_documents({"session_id": session_id})
        
        new_summary = context_summary
        if msg_count >= 16 and settings.OPENAI_API_KEY:
            cursor = db.chat_messages.find({"session_id": session_id}).sort("created_at", 1)
            all_msgs = await cursor.to_list(length=100)
            
            summary_prompt = (
                "You are a conversation memory manager. Generate a concise summary of the following conversation history.\n"
                "Focus on the primary code modules, repositories, or topics discussed.\n"
                "Keep it under 200 words.\n\n"
                "Conversation History:\n"
            )
            for m in all_msgs:
                role = "User" if m["role"] == "user" else "Assistant"
                summary_prompt += f"{role}: {m['content']}\n"
            summary_prompt += "\nConcise Summary:"

            try:
                resp = await client.chat.completions.create(
                    model=settings.OPENAI_CHAT_MODEL,
                    messages=[{"role": "user", "content": summary_prompt}],
                    temperature=0.2,
                )
                new_summary = resp.choices[0].message.content.strip()
                logger.info(f"Generated rolling summary for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to generate rolling summary: {e}")

        # Update chat_session document
        try:
            update_data = {
                "message_count": msg_count,
                "updated_at": datetime.now(timezone.utc),
            }
            if new_summary != context_summary:
                update_data["context_summary"] = new_summary

            try:
                query_ids = [session_id]
                if ObjectId.is_valid(session_id):
                    query_ids.append(ObjectId(session_id))
                await db.chat_sessions.update_one({"_id": {"$in": query_ids}}, {"$set": update_data})
            except Exception as e:
                logger.error(f"Failed to update chat session: {e}")
        except Exception as e:
            logger.error(f"Failed to update chat session: {e}")

        # 7. Write audit log
        try:
            await db.audit_logs.insert_one({
                "user_id": user_id,
                "action": "chat_message",
                "resource_type": "session",
                "resource_id": session_id,
                "detail": f"Repo Chat query: {question[:100]}...",
                "ip_address": ip_address,
                "created_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")
