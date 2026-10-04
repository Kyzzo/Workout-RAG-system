"""
Replace one paper's chunks in the "literature" Qdrant collection: deletes
every chunk stored under its source id, then loads, chunks, embeds and
upserts the PDF again (same point-id scheme and payload as
app/rag/ingest.py). Runs directly - no Inngest dev server needed. Use it
when a paper's stored text is bad (e.g. extraction lost the spaces) or the
loader changed.

Note: Qdrant is shared by local and production, so this changes what the
live app retrieves immediately.

Usage (from backend/):
    uv run python -m scripts.reingest_literature <pdf_path> <category> <source_id>
"""

import argparse
import uuid
from typing import get_args

from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PayloadSchemaType

from app.rag.data_loader import embed_texts, load_and_chunk_pdf
from app.rag.qdrant_storage import QdrantStorage
from app.rag.types import Category

VALID_CATEGORIES = set(get_args(Category))
_EMBED_BATCH = 64


def main():
    parser = argparse.ArgumentParser(description="Re-ingest one PDF, replacing its old chunks")
    parser.add_argument("pdf_path")
    parser.add_argument("category", choices=sorted(VALID_CATEGORIES))
    parser.add_argument("source_id", help="The source id its chunks are stored under")
    args = parser.parse_args()

    chunks = load_and_chunk_pdf(args.pdf_path)
    if not chunks:
        raise SystemExit("No text extracted - nothing replaced.")
    vectors = []
    for start in range(0, len(chunks), _EMBED_BATCH):
        vectors += embed_texts(chunks[start:start + _EMBED_BATCH])

    storage = QdrantStorage(collection="literature")
    # Qdrant Cloud only filters on indexed fields; creating an existing
    # index is a no-op.
    storage.client.create_payload_index(storage.collection, "source", field_schema=PayloadSchemaType.KEYWORD, wait=True)
    source_filter = Filter(must=[FieldCondition(key="source", match=MatchValue(value=args.source_id))])
    before = storage.client.count(storage.collection, count_filter=source_filter, exact=True).count
    # Delete first: the new extraction can yield fewer chunks than the old,
    # and leftover old ids would otherwise stay retrievable.
    storage.client.delete(storage.collection, points_selector=FilterSelector(filter=source_filter), wait=True)
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{args.source_id}:{i}")) for i in range(len(chunks))]
    payloads = [{"source": args.source_id, "text": text, "category": args.category} for text in chunks]
    storage.upsert(ids, vectors, payloads)
    after = storage.client.count(storage.collection, count_filter=source_filter, exact=True).count
    print(f"{args.source_id}: replaced {before} chunks with {after}")
    print("Next: scripts.clear_shared_answers and scripts.refresh_rule_justifications (local and production).")


if __name__ == "__main__":
    main()
