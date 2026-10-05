"""
Trigger ingestion of one paper into the "literature" Qdrant collection.
The paper must be listed in corpus/papers.json first - its PDF path,
categories and tags come from there.

Requires both the FastAPI app and the Inngest dev server running:
    uvicorn app.main:app --port 8000 --reload
    npx inngest-cli@latest dev -u http://localhost:8000/api/inngest

Usage:
    uv run python -m scripts.ingest_literature <source_id>

For a quick re-ingest without Inngest, see scripts/reingest_literature.py.
"""

import argparse
import asyncio

import inngest

from app.rag.corpus import paper
from app.rag.ingest import inngest_client


async def main():
    parser = argparse.ArgumentParser(description="Ingest a paper listed in corpus/papers.json")
    parser.add_argument("source_id")
    args = parser.parse_args()
    paper(args.source_id)  # fail fast if it isn't in the manifest

    event_ids = await inngest_client.send(
        inngest.Event(name="rag/ingest_literature", data={"source_id": args.source_id})
    )
    print(f"Sent event {event_ids[0]} — check the Inngest dashboard (localhost:8288) for run status.")


if __name__ == "__main__":
    asyncio.run(main())
