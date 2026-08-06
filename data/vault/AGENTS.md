# Wiki Maintainer Schema

This vault follows a three-layer workflow:

1. `raw/` stores immutable source material copied from repositories and uploaded documents.
2. `wiki/` stores generated markdown notes, summaries, indexes, and logs.
3. `graphify-out/` stores graph artifacts generated from the wiki layer.

Operational rules:
- Never edit files under `raw/`.
- Add new synthesized notes under `wiki/`.
- Update `wiki/index.md` and `wiki/log.md` whenever a source is ingested.
- Prefer linking related notes instead of duplicating long passages.
- Treat repository overviews and document notes as durable pages that can be refined over time.
