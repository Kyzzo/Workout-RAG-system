"""
Trigger ingestion of a single PDF into the "literature" Qdrant collection.

Requires both the FastAPI app and the Inngest dev server running:
    uvicorn app.main:app --port 8000 --reload
    npx inngest-cli@latest dev -u http://localhost:8000/api/inngest

Usage:
    uv run python -m scripts.ingest_literature <pdf_path> <category> [source_id]

    category must be one of: volume, frequency, intensity, progression
"""

import argparse
import asyncio
import sys

import inngest

from app.rag.ingest import inngest_client

VALID_CATEGORIES = {"volume", "frequency", "intensity", "progression"}


async def main():
    parser = argparse.ArgumentParser(description="Ingest a PDF into the literature collection")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("category", choices=sorted(VALID_CATEGORIES))
    parser.add_argument("source_id", nargs="?", default=None, help="Defaults to the pdf_path")
    args = parser.parse_args()

    event_ids = await inngest_client.send(
        inngest.Event(
            name="rag/ingest_literature",
            data={
                "pdf_path": args.pdf_path,
                "category": args.category,
                "source_id": args.source_id or args.pdf_path,
            },
        )
    )
    print(f"Sent event {event_ids[0]} — check the Inngest dashboard (localhost:8288) for run status.")


if __name__ == "__main__":
    asyncio.run(main())
