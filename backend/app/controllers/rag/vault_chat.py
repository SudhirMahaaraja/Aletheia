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


class VaultChatService:
    @staticmethod
    async def stream_response(
        db,
        session_id: str,
        user_id: str,
        question: str,
        chat_history: list,
        ip_address: str = "",
    ):
        """
        Streams a RAG response for Vault Chat (uploaded company documents only).
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

        # 2. Reformulate the query if there is history
        rewritten_query = question
        if chat_history and settings.OPENAI_API_KEY:
            reformulation_prompt = (
                "Given the following conversation summary and recent turn history, and a follow-up question, "
                "rephrase the follow-up question to be a standalone search query that captures all necessary context, "
                "specifically targeting relevant concepts, documents, or terms discussed.\n"
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

        # 3. Retrieve document chunks using HybridRetriever
        enriched_chunks = await HybridRetriever.retrieve(
            db=db,
            query=rewritten_query,
            mode="vault",
            top_k=5,
        )

        context_str = ""
        sources = []
        for chunk in enriched_chunks:
            payload = chunk["payload"]
            doc_title = payload.get("document_title", "Untitled Document")
            sec_heading = payload.get("section_heading", "")
            content = payload.get("content", "")
            
            source_info = f"Document: {doc_title}"
            if sec_heading:
                source_info += f" | Section: {sec_heading}"
            
            context_str += f"[{source_info}]\n{content}\n"
            
            # Enrich relationships if any
            if chunk["relationships"]:
                context_str += "Graph Relationships:\n"
                for rel in chunk["relationships"]:
                    context_str += f"- {rel}\n"
            context_str += "---\n\n"

            sources.append({
                "document_id": str(payload.get("document_id")) if payload.get("document_id") is not None else "",
                "document_title": doc_title,
                "section_heading": sec_heading,
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
            "You are the BWS Second Brain — an internal knowledge assistant for BinaryWaves Solutions.\n"
            "Your primary purpose is to answer questions using company document content provided in the context below.\n"
            "Be highly specific and accurate. Quote or refer to details in the documents directly.\n"
            "If the documents do not contain the answer to a specific question, clearly state that the information is not in the uploaded documents, and offer to help with what you do know.\n"
            "For greetings, small talk, or general questions unrelated to documents, respond naturally and helpfully — no need to reference documents.\n"
            "When referencing documents, always mention the exact document titles and sections you are referring to."
        )

        if context_summary:
            system_prompt += f"\n\nHere is a summary of the conversation history for context:\n{context_summary}"

        messages = [
            {"role": "system", "content": f"{system_prompt}\n\nDocument Context:\n{context_str or 'No relevant document content found.'}"}
        ]

        # Append last 4 messages of history to avoid context window explosion
        for msg in chat_history[-4:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": question})

        full_answer = ""
        try:
            if not settings.OPENAI_API_KEY:
                fallback = (
                    "OpenAI API key is missing. However, here is the relevant document context matching your question:\n\n"
                    f"{context_str or 'No matching document chunks found.'}"
                )
                yield f"data: {json.dumps({'token': fallback})}\n\n"
                full_answer = fallback
            else:
                stream = await client.chat.completions.create(
                    model=settings.OPENAI_CHAT_MODEL,
                    messages=messages,
                    temperature=0.2,
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
            src["node_id"] = src.get("chunk_id")

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
        # Get count of messages in this session
        msg_count = await db.chat_messages.count_documents({"session_id": session_id})
        
        # Summarize if count >= 16 (8 turns)
        new_summary = context_summary
        if msg_count >= 16 and settings.OPENAI_API_KEY:
            # Fetch all messages in the session ordered by created_at
            cursor = db.chat_messages.find({"session_id": session_id}).sort("created_at", 1)
            all_msgs = await cursor.to_list(length=100)
            
            summary_prompt = (
                "You are a conversation memory manager. Generate a concise summary of the following conversation history.\n"
                "Focus on the primary topics discussed, the document titles referenced, and specific user queries.\n"
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
                "detail": f"Vault Chat query: {question[:100]}...",
                "ip_address": ip_address,
                "created_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")
