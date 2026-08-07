import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.controllers import github_controller
from app.controllers.ingestion.chunker import ChunkRouter
from app.controllers.ingestion.embedder import embed_chunks
from app.controllers.ingestion.graph_builder import build_graph_from_repo, build_graph_from_document_chunks, build_similar_edges, build_overall_graph
from app.controllers.ingestion.parsers.base_parser import ParsedChunk
from app.controllers.ingestion.parsers import document_parser
from app.controllers.vault_manager import (
    append_log_entry,
    build_document_page,
    copy_file,
    ensure_vault_structure,
    rebuild_index,
    render_repo_source_page,
    repo_slug,
    reset_directory,
    resolve_vault_dir,
    slugify,
    write_repo_overview,
)

logger = logging.getLogger(__name__)

_ingestion_semaphore = asyncio.Semaphore(1)


async def sync_wiki_meta_to_db(vault_dir: Path, db) -> None:
    """Re-read wiki/index.md and wiki/log.md from disk and upsert their
    content into document_chunks so the frontend WikiPage shows current data."""
    wiki_root = vault_dir / "wiki"
    meta_files = {
        "index.md": wiki_root / "index.md",
        "log.md": wiki_root / "log.md",
    }

    for rel_name, file_path in meta_files.items():
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")

        # Find the matching Document graph_node by file_path
        node = await db.graph_nodes.find_one(
            {"type": "Document", "file_path": rel_name}
        )
        if not node:
            continue

        node_id = node["_id"]
        now = datetime.now(timezone.utc)

        # Upsert a single document_chunk containing the full content
        await db.document_chunks.update_one(
            {"document_id": node_id, "page_number": 0},
            {"$set": {
                "content": content,
                "document_id": node_id,
                "page_number": 0,
                "updated_at": now,
            }, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

        # Update the graph_node summary with the first line of content
        first_heading = content.split("\n", 1)[0].lstrip("# ").strip()
        await db.graph_nodes.update_one(
            {"_id": node_id},
            {"$set": {"summary": first_heading, "updated_at": now}},
        )

    logger.info("Synced wiki meta files (index.md, log.md) to document_chunks")

async def ingest_repository(
    job_id: str,
    repo_full_name: str,
    branch: str,
    db,
) -> None:
    async with _ingestion_semaphore:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        temp_dir = tempfile.mkdtemp()

        try:
            # Check if job was deleted/cancelled before starting
            job = await db.ingestion_jobs.find_one({"_id": job_id})
            if not job:
                logger.info("Ingestion job %s was deleted/cancelled before starting. Aborting.", job_id)
                return

            # Mark job as running
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {"status": "running", "started_at": now}},
            )

            # Clear existing chunks and graph data for this repo
            await db.code_chunks.delete_many({"repo_name": repo_full_name})
            # Get node IDs for this repo so we can delete related edges
            repo_node_ids = []
            async for node in db.graph_nodes.find({"repo_name": repo_full_name}, {"_id": 1}):
                repo_node_ids.append(node["_id"])
            if repo_node_ids:
                await db.graph_edges.delete_many({
                    "$or": [
                        {"from_id": {"$in": repo_node_ids}},
                        {"to_id": {"$in": repo_node_ids}},
                    ]
                })
            await db.graph_nodes.delete_many({"repo_name": repo_full_name})

            # Fetch PAT from DB connections
            conn = await db.github_connections.find_one({"active": True})
            db_pat = conn.get("pat", "") if conn else ""
            clone_url = f"https://{db_pat}@github.com/{repo_full_name}.git" if db_pat else f"https://github.com/{repo_full_name}.git"
            def run_clone():
                return subprocess.run(
                    ["git", "clone", "--depth=1", "--branch", branch, clone_url, temp_dir],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            res = await asyncio.to_thread(run_clone)
            if res.returncode != 0:
                raise RuntimeError(f"Git clone failed for {repo_full_name}: {res.stderr.decode(errors='ignore')}")

            # Run design systems analyst extractor right after git clone
            from app.controllers.ingestion import design_extractor
            import hashlib
            repo_doc = await db.repositories.find_one({"github_full_name": repo_full_name})
            project_description = repo_doc.get("description", "") if repo_doc else ""
            design_md_content = await design_extractor.generate_design_md(
                repo_name=repo_full_name, repo_dir=temp_dir, project_description=project_description
            )
            if design_md_content:
                from app.controllers import vault_manager
                vault_manager.write_design_doc(repo_full_name, design_md_content)
                
                # Fetch target graph node IDs
                repo_id_str = f"repo:{repo_full_name}"
                repository_id = hashlib.sha256(repo_id_str.encode()).hexdigest()[:24]
                project_id = repo_doc.get("project_id") if repo_doc else None
                await design_extractor.register_design_node(
                    repo_name=repo_full_name,
                    repository_id=repository_id,
                    project_id=project_id,
                    content=design_md_content,
                    db=db
                )


            # Fetch file tree
            file_tree = await github_controller.fetch_repo_file_tree(repo_full_name, branch, db)
            total_files = len(file_tree)

            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {"files_total": total_files}},
            )

            if total_files == 0:
                logger.warning("No eligible files found in %s@%s", repo_full_name, branch)
                await db.ingestion_jobs.update_one(
                    {"_id": job_id},
                    {"$set": {"status": "done", "completed_at": datetime.now(timezone.utc)}},
                )
                return

            semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_FILES)
            total_chunk_ids: list[str] = []
            files_processed = 0
            errors: list[str] = []

            async def process_single_file(file_info):
                nonlocal files_processed
                async with semaphore:
                    try:
                        file_path_on_disk = os.path.join(temp_dir, file_info.path)
                        if not os.path.exists(file_path_on_disk):
                            files_processed += 1
                            logger.warning("[%s] [%d/%d] SKIP (not on disk): %s",
                                           repo_full_name, files_processed, total_files, file_info.path)
                            return

                        # Read file contents in executor
                        def read_file_sync():
                            with open(file_path_on_disk, "r", encoding="utf-8", errors="ignore") as f:
                                return f.read()
                        content = await asyncio.to_thread(read_file_sync)

                        parser = ChunkRouter.get_parser(file_info.path)
                        if parser:
                            parser_label = type(parser).__name__
                            chunks = parser.parse(content, file_info.path)
                        elif file_info.path.lower().endswith((".md", ".markdown")):
                            parser_label = "MarkdownParser"
                            chunks = await document_parser.parse_markdown(content, file_info.path)
                        elif file_info.path.lower().endswith((".txt", ".text")) or file_info.path.split("/")[-1].lower() == "readme":
                            parser_label = "TextParser"
                            chunks = await document_parser.parse_txt(content, file_info.path)
                        else:
                            from app.controllers.ingestion.parsers.base_parser import post_process_chunks, detect_language
                            parser_label = "FallbackParser"
                            chunks = post_process_chunks([ParsedChunk(
                                chunk_type="file",
                                name=file_info.path.split("/")[-1],
                                content=content,
                                language=detect_language(file_info.path),
                                file_path=file_info.path,
                                line_start=1,
                                line_end=len(content.splitlines()),
                                imports=[],
                                calls=[],
                            )])

                        chunk_count = len(chunks) if chunks else 0
                        files_processed += 1
                        curr_processed = files_processed

                        logger.info("[%s] [%d/%d] %-20s  chunks=%-4d  %s",
                                    repo_full_name, curr_processed, total_files,
                                    parser_label, chunk_count, file_info.path)

                        # Embed this file's chunks immediately and free them
                        if chunks:
                            chunk_ids = await embed_chunks(
                                chunks=chunks,
                                collection="code_chunks",
                                db=db,
                                repo_name=repo_full_name,
                            )
                            total_chunk_ids.extend(chunk_ids)

                        # Progress summary every 10 files
                        if curr_processed % 10 == 0:
                            logger.info("[%s] Progress: %d/%d files done, %d chunks total so far",
                                        repo_full_name, curr_processed, total_files, len(total_chunk_ids))

                    except Exception as exc:
                        msg = f"Error processing {file_info.path}: {exc}"
                        files_processed += 1
                        curr_processed = files_processed
                        logger.error("[%s] [%d/%d] ERROR: %s", repo_full_name, curr_processed, total_files, msg)
                        errors.append(msg)

                    finally:
                        await db.ingestion_jobs.update_one(
                            {"_id": job_id},
                            {"$set": {"files_processed": files_processed, "current_file": file_info.path}},
                        )

            tasks = [process_single_file(f) for f in file_tree]
            await asyncio.gather(*tasks)

            logger.info("Parsed %d chunks from %d files in %s", len(total_chunk_ids), total_files, repo_full_name)

            # Build graph using Graphify on temp_dir
            if total_chunk_ids:
                nodes_created, edges_created = await build_graph_from_repo(repo_full_name, temp_dir, db)

                # Build SIMILAR_TO edges
                similar_edges = await build_similar_edges(repo_full_name, db)
                edges_created += similar_edges
            else:
                nodes_created = 0
                edges_created = 0

            # Update job and repo
            completed_at = datetime.now(timezone.utc)
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "done",
                    "files_processed": files_processed,
                    "chunks_created": len(total_chunk_ids),
                    "nodes_created": nodes_created,
                    "edges_created": edges_created,
                    "errors": errors[:50],
                    "completed_at": completed_at,
                }},
            )

            await db.repositories.update_one(
                {"github_full_name": repo_full_name},
                {"$set": {
                    "ingestion_status": "done",
                    "last_ingested_at": completed_at,
                    "total_files": files_processed,
                    "total_chunks": len(total_chunk_ids),
                }},
            )

            from app.controllers.ingestion.graph_builder import update_index_connections
            await update_index_connections(db)

            logger.info(
                "Ingestion complete for %s: %d chunks, %d nodes, %d edges",
                repo_full_name, len(total_chunk_ids), nodes_created, edges_created,
            )

        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", repo_full_name, exc, exc_info=True)
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "failed",
                    "errors": [str(exc)],
                    "completed_at": datetime.now(timezone.utc),
                }},
            )
            await db.repositories.update_one(
                {"github_full_name": repo_full_name},
                {"$set": {"ingestion_status": "failed"}},
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            import gc
            gc.collect()


async def ingest_document(
    job_id: str,
    document_id: str,
    file_bytes: bytes,
    filename: str,
    file_type: str,
    db,
) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    try:
        # Check if job was deleted/cancelled before starting
        job = await db.ingestion_jobs.find_one({"_id": job_id})
        if not job:
            logger.info("Ingestion job %s was deleted/cancelled before starting. Aborting.", job_id)
            return

        await db.ingestion_jobs.update_one(
            {"_id": job_id},
            {"$set": {"status": "running", "started_at": now}},
        )

        document_doc = await db.documents.find_one({"_id": document_id}) or {}
        title = document_doc.get("title") or filename
        vault_dir = resolve_vault_dir(settings.VAULT_PATH)
        paths = ensure_vault_structure(vault_dir)

        # Parse document based on type
        if file_type == "pdf":
            chunks = await document_parser.parse_pdf(file_bytes, filename)
        elif file_type == "docx":
            chunks = await document_parser.parse_docx(file_bytes, filename)
        elif file_type == "md":
            content = file_bytes.decode("utf-8", errors="replace")
            chunks = await document_parser.parse_markdown(content, filename)
        elif file_type == "txt":
            content = file_bytes.decode("utf-8", errors="replace")
            chunks = await document_parser.parse_txt(content, filename)
        else:
            chunks = []

        doc_slug = f"{slugify(Path(title).stem)}-{document_id[:8]}"
        raw_doc_path = paths["raw_documents"] / f"{doc_slug}.{file_type}"
        raw_doc_path.write_bytes(file_bytes)

        raw_rel_path = os.path.relpath(raw_doc_path, vault_dir).replace('\\', '/')
        wiki_doc_path = paths["wiki_documents"] / f"{doc_slug}.md"
        wiki_doc_path.write_text(
            build_document_page(
                title=title,
                original_filename=filename,
                raw_rel_path=raw_rel_path,
                file_type=file_type,
                chunks=chunks,
            ),
            encoding="utf-8",
        )

        rebuild_index(vault_dir)
        append_log_entry(
            vault_dir,
            "document",
            title,
            [
                f"document_id: `{document_id}`",
                f"raw copy: `{raw_rel_path}`",
                f"wiki note: `{wiki_doc_path.relative_to(vault_dir).as_posix()}`",
                f"parsed chunks: {len(chunks)}",
            ],
        )

        if not chunks:
            await db.documents.update_one(
                {"_id": document_id},
                {"$set": {
                    "ingestion_status": "done",
                    "total_chunks": 0,
                    "vault_raw_path": raw_rel_path,
                    "vault_wiki_path": wiki_doc_path.relative_to(vault_dir).as_posix(),
                }},
            )
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "done",
                    "chunks_created": 0,
                    "completed_at": datetime.now(timezone.utc),
                }},
            )
            await sync_wiki_meta_to_db(vault_dir, db)
            from app.controllers.ingestion.graph_builder import update_index_connections
            await update_index_connections(db)
            await build_overall_graph(str(vault_dir), db)
            return

        # Embed and store
        chunk_ids = await embed_chunks(
            chunks=chunks,
            collection="document_chunks",
            db=db,
            document_id=document_id,
            document_title=filename,
        )

        # Create graph nodes for document chunks and build document graph structure
        nodes_created, edges_created = await build_graph_from_document_chunks(
            chunks=chunks,
            chunk_ids=chunk_ids,
            document_id=document_id,
            db=db
        )

        completed_at = datetime.now(timezone.utc)
        await db.ingestion_jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "done",
                "chunks_created": len(chunk_ids),
                "nodes_created": nodes_created,
                "edges_created": edges_created,
                "completed_at": completed_at,
            }},
        )
        await db.documents.update_one(
            {"_id": document_id},
            {"$set": {
                "ingestion_status": "done",
                "total_chunks": len(chunk_ids),
                "vault_raw_path": raw_rel_path,
                "vault_wiki_path": wiki_doc_path.relative_to(vault_dir).as_posix(),
            }},
        )

        await build_overall_graph(str(vault_dir), db)
        await sync_wiki_meta_to_db(vault_dir, db)
        from app.controllers.ingestion.graph_builder import update_index_connections
        await update_index_connections(db)

        logger.info("Document %s ingested: %d chunks", filename, len(chunk_ids))

    except Exception as exc:
        logger.error("Document ingestion failed for %s: %s", filename, exc, exc_info=True)
        await db.ingestion_jobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "failed",
                "errors": [str(exc)],
                "completed_at": datetime.now(timezone.utc),
            }},
        )
        await db.documents.update_one(
            {"_id": document_id},
            {"$set": {"ingestion_status": "failed"}},
        )


async def ingest_repo_to_local_vault(
    job_id: str,
    repo_full_name: str,
    branch: str,
    db,
) -> None:
    async with _ingestion_semaphore:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        temp_dir = tempfile.mkdtemp()

        try:
            # Check if job was deleted/cancelled before starting
            job = await db.ingestion_jobs.find_one({"_id": job_id})
            if not job:
                logger.info("Ingestion job %s was deleted/cancelled before starting. Aborting.", job_id)
                return

            # Mark job as running
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {"status": "running", "started_at": now}},
            )

            # Fetch PAT from DB connections
            conn = await db.github_connections.find_one({"active": True})
            db_pat = conn.get("pat", "") if conn else ""
            clone_url = f"https://{db_pat}@github.com/{repo_full_name}.git" if db_pat else f"https://github.com/{repo_full_name}.git"

            def run_clone():
                return subprocess.run(
                    ["git", "clone", "--depth=1", "--branch", branch, clone_url, temp_dir],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            res = await asyncio.to_thread(run_clone)
            if res.returncode != 0:
                raise RuntimeError(f"Git clone failed for {repo_full_name}: {res.stderr.decode(errors='ignore')}")

            # Run design systems analyst extractor right after git clone
            from app.controllers.ingestion import design_extractor
            import hashlib as _hashlib
            repo_doc_vault = await db.repositories.find_one({"github_full_name": repo_full_name})
            _proj_desc = repo_doc_vault.get("description", "") if repo_doc_vault else ""
            _design_md = await design_extractor.generate_design_md(
                repo_name=repo_full_name, repo_dir=temp_dir, project_description=_proj_desc
            )
            if _design_md:
                from app.controllers import vault_manager as _vm
                _vm.write_design_doc(repo_full_name, _design_md)
                _repo_id = _hashlib.sha256(f"repo:{repo_full_name}".encode()).hexdigest()[:24]
                _proj_id = repo_doc_vault.get("project_id") if repo_doc_vault else None
                await design_extractor.register_design_node(
                    repo_name=repo_full_name,
                    repository_id=_repo_id,
                    project_id=_proj_id,
                    content=_design_md,
                    db=db,
                )

            # Fetch file tree configuration constants
            from app.controllers.github_controller import SKIP_DIRS, ALLOWED_EXTENSIONS, MAX_FILE_SIZE
            from bson import ObjectId

            vault_dir = resolve_vault_dir(settings.VAULT_PATH)
            paths = ensure_vault_structure(vault_dir)
            repo_key = repo_slug(repo_full_name)
            raw_repo_dir = paths["raw_repositories"] / repo_key
            wiki_repo_dir = paths["wiki_repositories"] / repo_key
            wiki_sources_dir = wiki_repo_dir / "sources"
            repo_graph_dir = paths["repo_graphs"] / repo_key

            reset_directory(raw_repo_dir)
            reset_directory(wiki_repo_dir)
            wiki_sources_dir.mkdir(parents=True, exist_ok=True)
            reset_directory(repo_graph_dir)

            # Walk temp_dir and locate files matching extension configurations
            files_to_process = []
            for root, dirs, files in os.walk(temp_dir):
                # Prune SKIP_DIRS
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    is_readme = file.lower().startswith("readme")
                    if ext in ALLOWED_EXTENSIONS or is_readme:
                        full_path = os.path.join(root, file)
                        if os.path.getsize(full_path) <= MAX_FILE_SIZE:
                            rel_path = os.path.relpath(full_path, temp_dir)
                            files_to_process.append((full_path, rel_path, ext))

            total_files = len(files_to_process)
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {"files_total": total_files}},
            )

            semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_FILES)
            files_processed = 0
            chunks_created = 0
            nodes_created = 0
            edges_created = 0
            errors = []

            async def process_single_file_vault(full_path, rel_path, ext):
                nonlocal files_processed, chunks_created, nodes_created, edges_created
                async with semaphore:
                    try:
                        await db.ingestion_jobs.update_one(
                            {"_id": job_id},
                            {"$set": {"current_file": rel_path}}
                        )
                        # Read file contents in executor
                        def read_file_sync():
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                return f.read()
                        content = await asyncio.to_thread(read_file_sync)

                        raw_target = raw_repo_dir / rel_path
                        # Run file system writing operations in executor
                        def write_files_sync():
                            copy_file(full_path, raw_target)
                            vault_file_path = wiki_sources_dir / f"{rel_path}.md"
                            vault_file_path.parent.mkdir(parents=True, exist_ok=True)
                            raw_rel_path_str = os.path.relpath(raw_target, vault_dir).replace('\\', '/')
                            v_content = render_repo_source_page(
                                repo_full_name=repo_full_name,
                                rel_path=rel_path,
                                raw_rel_path=raw_rel_path_str,
                                content=content,
                                ext=ext,
                            )
                            vault_file_path.write_text(v_content, encoding="utf-8")
                            return vault_file_path, raw_rel_path_str, v_content

                        vault_file_path, raw_rel_path, vault_content = await asyncio.to_thread(write_files_sync)

                        # Now parse and ingest the document to DB
                        doc_chunks = await document_parser.parse_markdown(vault_content, vault_file_path.name)
                        if doc_chunks:
                            doc_id = str(ObjectId())
                            now_ts = datetime.now(timezone.utc)

                            # Create document record in DB
                            doc_record = {
                                "_id": doc_id,
                                "title": os.path.basename(rel_path),
                                "original_filename": rel_path,
                                "file_type": "md",
                                "project_id": None,
                                "uploaded_by": "system",
                                "uploaded_at": now_ts,
                                "ingestion_status": "done",
                                "total_chunks": len(doc_chunks),
                                "file_size_bytes": len(vault_content.encode("utf-8")),
                                "repo_name": repo_full_name,
                                "vault_raw_path": raw_rel_path,
                                "vault_wiki_path": vault_file_path.relative_to(vault_dir).as_posix(),
                            }
                            await db.documents.insert_one(doc_record)

                            # Embed and store
                            chunk_ids = await embed_chunks(
                                chunks=doc_chunks,
                                collection="document_chunks",
                                db=db,
                                document_id=doc_id,
                                document_title=os.path.basename(rel_path),
                            )

                            # Build lightweight graph nodes inline
                            await db.graph_nodes.update_one(
                                {"_id": doc_id},
                                {"$set": {
                                    "type": "Document",
                                    "name": os.path.basename(rel_path),
                                    "file_path": rel_path,
                                    "updated_at": now_ts,
                                }, "$setOnInsert": {"created_at": now_ts}},
                                upsert=True,
                            )
                            
                            local_nodes_created = 1
                            local_edges_created = 0

                            for chunk, cid in zip(doc_chunks, chunk_ids):
                                await db.graph_nodes.update_one(
                                    {"_id": cid},
                                    {"$set": {
                                        "type": "Section",
                                        "name": chunk.name,
                                        "file_path": rel_path,
                                        "language": chunk.language or "text",
                                        "updated_at": now_ts,
                                    }, "$setOnInsert": {"created_at": now_ts}},
                                    upsert=True,
                                )
                                await db.graph_edges.update_one(
                                    {"from_id": cid, "to_id": doc_id, "type": "PART_OF"},
                                    {"$setOnInsert": {
                                        "from_id": cid, "to_id": doc_id,
                                        "type": "PART_OF", "weight": None, "created_at": now_ts,
                                    }},
                                    upsert=True,
                                )
                                local_nodes_created += 1
                                local_edges_created += 1

                            files_processed += 1
                            chunks_created += len(chunk_ids)
                            nodes_created += local_nodes_created
                            edges_created += local_edges_created
                        else:
                            files_processed += 1

                    except Exception as e:
                        msg = f"Error processing {rel_path}: {e}"
                        logger.error(msg)
                        errors.append(msg)
                        files_processed += 1

                    finally:
                        await db.ingestion_jobs.update_one(
                            {"_id": job_id},
                            {"$set": {"files_processed": files_processed, "chunks_created": chunks_created}},
                        )

            tasks = [process_single_file_vault(fp, rp, ex) for fp, rp, ex in files_to_process]
            await asyncio.gather(*tasks)

            # Build codebase graph using Graphify on temp_dir
            repo_nodes, repo_edges = await build_graph_from_repo(repo_full_name, temp_dir, db)
            nodes_created += repo_nodes
            edges_created += repo_edges

            write_repo_overview(
                wiki_repo_dir=wiki_repo_dir,
                repo_full_name=repo_full_name,
                branch=branch,
                rel_paths=[rel_path for _, rel_path, _ in files_to_process],
                repo_graph_dir=repo_graph_dir,
            )

            # Copy the generated graphify-out directory to vault
            temp_graphify_out = os.path.join(temp_dir, "graphify-out")
            if os.path.exists(temp_graphify_out):
                reset_directory(repo_graph_dir)
                shutil.copytree(temp_graphify_out, repo_graph_dir, dirs_exist_ok=True)
                logger.info("Saved repository graphify-out to vault: %s", repo_graph_dir)

            rebuild_index(vault_dir)
            raw_mirror_rel = os.path.relpath(raw_repo_dir, vault_dir).replace('\\', '/')
            wiki_notes_rel = wiki_repo_dir.relative_to(vault_dir).as_posix()
            append_log_entry(
                vault_dir,
                "repository",
                repo_full_name,
                [
                    f"branch: `{branch}`",
                    f"raw mirror: `{raw_mirror_rel}`",
                    f"wiki notes: `{wiki_notes_rel}`",
                    f"supported files: {total_files}",
                    f"chunks created: {chunks_created}",
                ],
            )

            # Skip build_overall_graph during ingestion to avoid memory spike from
            # spawning a second graphify subprocess. It can be triggered separately.
            await sync_wiki_meta_to_db(vault_dir, db)
            from app.controllers.ingestion.graph_builder import update_index_connections
            await update_index_connections(db)

            # Complete job
            completed_at = datetime.now(timezone.utc)
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "done",
                    "files_processed": files_processed,
                    "chunks_created": chunks_created,
                    "nodes_created": nodes_created,
                    "edges_created": edges_created,
                    "errors": errors[:50],
                    "completed_at": completed_at,
                }},
            )

            await db.repositories.update_one(
                {"github_full_name": repo_full_name},
                {"$set": {
                    "ingestion_status": "done",
                    "last_ingested_at": completed_at,
                    "total_files": files_processed,
                    "total_chunks": chunks_created,
                    "vault_raw_path": os.path.relpath(raw_repo_dir, vault_dir).replace('\\', '/'),
                    "vault_wiki_path": wiki_repo_dir.relative_to(vault_dir).as_posix(),
                    "vault_repo_graph_path": os.path.relpath(repo_graph_dir, vault_dir).replace('\\', '/'),
                }},
            )

        except Exception as exc:
            logger.error("Vault Ingestion failed for %s: %s", repo_full_name, exc, exc_info=True)
            await db.ingestion_jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    "status": "failed",
                    "errors": [str(exc)],
                    "completed_at": datetime.now(timezone.utc),
                }},
            )
            await db.repositories.update_one(
                {"github_full_name": repo_full_name},
                {"$set": {"ingestion_status": "failed"}},
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            import gc
            gc.collect()


async def sync_vault_to_db(db) -> None:
    """Scan the local vault directory on disk and synchronize its contents (documents,
    repositories, files) with the MongoDB collections (documents, repositories, graph_nodes,
    document_chunks, code_chunks)."""
    import hashlib
    from datetime import datetime, timezone
    from bson import ObjectId
    
    settings = get_settings()
    vault_dir = resolve_vault_dir(settings.VAULT_PATH)
    paths = ensure_vault_structure(vault_dir)
    now = datetime.now(timezone.utc)
    
    logger.info("Syncing local vault from disk (%s) to MongoDB...", vault_dir)

    # 1. Sync Wiki Documents
    wiki_docs_dir = paths["wiki_documents"]
    if wiki_docs_dir.exists():
        for doc_file in wiki_docs_dir.glob("*.md"):
            try:
                content = doc_file.read_text(encoding="utf-8", errors="ignore")
                
                # Parse frontmatter
                frontmatter = {}
                lines = content.splitlines()
                if len(lines) > 0 and lines[0].strip() == "---":
                    fm_lines = []
                    for line in lines[1:]:
                        if line.strip() == "---":
                            break
                        fm_lines.append(line)
                    for fm_line in fm_lines:
                        if ":" in fm_line:
                            key, val = fm_line.split(":", 1)
                            frontmatter[key.strip()] = val.strip()
                
                # Extract title (usually first # heading)
                title = doc_file.stem
                for line in lines:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                        
                slug = doc_file.stem
                suffix = ""
                if "-" in slug:
                    parts = slug.split("-")
                    if len(parts[-1]) == 8 and all(c in "0123456789abcdefABCDEF" for c in parts[-1]):
                        suffix = parts[-1]
                
                # Create a deterministic 24-character hex ID
                if suffix:
                    doc_id = suffix + "0" * 16
                else:
                    doc_id = hashlib.sha256(slug.encode()).hexdigest()[:24]
                
                original_filename = frontmatter.get("original_filename") or f"{slug}.{frontmatter.get('file_type', 'txt')}"
                file_type = frontmatter.get("file_type") or doc_file.suffix[1:] or "txt"
                raw_path = frontmatter.get("raw_path") or f"raw/documents/{slug}.{file_type}"
                chunk_count = int(frontmatter.get("chunk_count") or 1)
                
                # Check/upsert document
                doc_record = {
                    "title": title,
                    "original_filename": original_filename,
                    "file_type": file_type,
                    "project_id": None,
                    "uploaded_by": "system_sync",
                    "uploaded_at": now,
                    "ingestion_status": "done",
                    "total_chunks": chunk_count,
                    "file_size_bytes": len(content.encode("utf-8")),
                    "vault_raw_path": raw_path,
                    "vault_wiki_path": doc_file.relative_to(vault_dir).as_posix(),
                }
                await db.documents.update_one(
                    {"_id": doc_id},
                    {"$set": doc_record, "$setOnInsert": {"_id": doc_id}},
                    upsert=True,
                )
                
                # Upsert Document Graph Node
                await db.graph_nodes.update_one(
                    {"_id": doc_id},
                    {"$set": {
                        "type": "Document",
                        "name": title,
                        "file_path": original_filename,
                        "updated_at": now,
                    }, "$setOnInsert": {"created_at": now}},
                    upsert=True,
                )
                
                # Upsert document chunk for the full content of the markdown page
                await db.document_chunks.update_one(
                    {"document_id": doc_id, "page_number": 0},
                    {"$set": {
                        "content": content,
                        "document_id": doc_id,
                        "page_number": 0,
                        "updated_at": now,
                    }, "$setOnInsert": {"created_at": now}},
                    upsert=True,
                )
                
                logger.info("Synced document note: %s (ID: %s)", title, doc_id)
            except Exception as e:
                logger.error("Failed to sync document file %s: %s", doc_file, e)

    # 2. Sync Repositories
    wiki_repos_dir = paths["wiki_repositories"]
    if wiki_repos_dir.exists():
        for repo_folder in wiki_repos_dir.iterdir():
            if not repo_folder.is_dir():
                continue
            overview_file = repo_folder / "overview.md"
            if not overview_file.exists():
                continue
            
            try:
                content = overview_file.read_text(encoding="utf-8", errors="ignore")
                
                # Parse frontmatter
                frontmatter = {}
                lines = content.splitlines()
                if len(lines) > 0 and lines[0].strip() == "---":
                    fm_lines = []
                    for line in lines[1:]:
                        if line.strip() == "---":
                            break
                        fm_lines.append(line)
                    for fm_line in fm_lines:
                        if ":" in fm_line:
                            key, val = fm_line.split(":", 1)
                            frontmatter[key.strip()] = val.strip()
                
                repo_name = frontmatter.get("repository") or repo_folder.name.replace("--", "/")
                branch = frontmatter.get("branch") or "main"
                file_count = int(frontmatter.get("file_count") or 0)
                
                # Upsert repo in DB
                repo_doc = {
                    "github_full_name": repo_name,
                    "name": repo_name.split("/")[-1],
                    "description": f"Repository {repo_name}",
                    "language": "text",
                    "selected_branch": branch,
                    "is_selected": True,
                    "ingestion_status": "done",
                    "total_files": file_count,
                    "total_chunks": 0,
                    "last_ingested_at": now,
                    "vault_raw_path": f"raw/repositories/{repo_folder.name}",
                    "vault_wiki_path": f"wiki/repositories/{repo_folder.name}",
                    "vault_repo_graph_path": f"graphs/repositories/{repo_folder.name}",
                }
                
                await db.repositories.update_one(
                    {"github_full_name": repo_name},
                    {"$set": repo_doc},
                    upsert=True,
                )
                
                # Recreate Repository Node
                repo_id_str = f"repo:{repo_name}"
                repo_node_id = hashlib.sha256(repo_id_str.encode()).hexdigest()[:24]
                await db.graph_nodes.update_one(
                    {"_id": repo_node_id},
                    {"$set": {
                        "type": "Repository",
                        "name": repo_name,
                        "repo_name": repo_name,
                        "file_path": "",
                        "language": "text",
                        "summary": f"Repository {repo_name}",
                        "updated_at": now,
                    }, "$setOnInsert": {"created_at": now}},
                    upsert=True,
                )
                
                # Recreate File Nodes & PART_OF connections
                sources_dir = repo_folder / "sources"
                if sources_dir.exists():
                    for src_file in sources_dir.rglob("*.md"):
                        try:
                            src_content = src_file.read_text(encoding="utf-8", errors="ignore")
                            src_lines = src_content.splitlines()
                            src_frontmatter = {}
                            if len(src_lines) > 0 and src_lines[0].strip() == "---":
                                src_fm_lines = []
                                for line in src_lines[1:]:
                                    if line.strip() == "---":
                                        break
                                    src_fm_lines.append(line)
                                for fm_line in src_fm_lines:
                                    if ":" in fm_line:
                                        key, val = fm_line.split(":", 1)
                                        src_frontmatter[key.strip()] = val.strip()
                            
                            rel_path = src_frontmatter.get("source_path")
                            raw_rel_path = src_frontmatter.get("raw_path")
                            
                            if not rel_path:
                                rel_path = src_file.relative_to(sources_dir).as_posix()
                                if rel_path.endswith(".md"):
                                    rel_path = rel_path[:-3]
                            
                            file_id_str = f"{repo_name}:{rel_path}::file"
                            file_node_id = hashlib.sha256(file_id_str.encode()).hexdigest()[:24]
                            
                            await db.graph_nodes.update_one(
                                {"_id": file_node_id},
                                {"$set": {
                                    "type": "File",
                                    "name": Path(rel_path).name,
                                    "repo_name": repo_name,
                                    "file_path": rel_path,
                                    "language": Path(rel_path).suffix[1:].lower() if Path(rel_path).suffix else "text",
                                    "summary": f"File {rel_path} in {repo_name}",
                                    "updated_at": now,
                                }, "$setOnInsert": {"created_at": now}},
                                upsert=True,
                            )
                            
                            await db.graph_edges.update_one(
                                {
                                    "from_id": file_node_id,
                                    "to_id": repo_node_id,
                                    "type": "PART_OF",
                                },
                                {"$set": {"weight": None, "created_at": now}},
                                upsert=True,
                            )
                            
                            # Skip loading raw file content during sync - code_chunks
                            # are created during ingestion with proper embeddings
                        except Exception as e:
                            logger.error("Failed to sync source file %s: %s", src_file, e)
                logger.info("Synced repository note: %s", repo_name)
            except Exception as e:
                logger.error("Failed to sync repo folder %s: %s", repo_folder, e)
                
    rebuild_index(vault_dir)

