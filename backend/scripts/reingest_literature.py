"""
(Re-)ingest one paper listed in corpus/papers.json, replacing any chunks
already stored under its source id: loads, chunks and embeds its PDF and
stores every chunk with the paper's tags (same point-id scheme as
app/rag/ingest.py). Runs directly - no Inngest dev server needed. Use it for
new papers and when a paper's stored text is bad or the loader changed. Tag
changes alone don't need this: run scripts/apply_paper_metadata.py.

Note: Qdrant is shared by local and production, so this changes what the
live app retrieves immediately.

Usage (from backend/):
    uv run python -m scripts.reingest_literature <source_id>
"""

import argparse
import uuid

from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PayloadSchemaType

from app.rag.corpus import paper
from app.rag.data_loader import embed_texts, load_and_chunk_pdf
from app.rag.qdrant_storage import REQUIRED_PAYLOAD_INDEXES, QdrantStorage

_EMBED_BATCH = 64


def main():
    parser = argparse.ArgumentParser(description="(Re-)ingest a paper listed in corpus/papers.json")
    parser.add_argument("source_id")
    args = parser.parse_args()
    entry = paper(args.source_id)

    chunks = load_and_chunk_pdf(str(entry.pdf_path))
    if not chunks:
        raise SystemExit("No text extracted - nothing replaced.")
    vectors = []
    for start in range(0, len(chunks), _EMBED_BATCH):
        vectors += embed_texts(chunks[start:start + _EMBED_BATCH])

    storage = QdrantStorage(collection="literature")
    # Qdrant Cloud only filters on indexed fields; creating an existing
    # index is a no-op.
    for field in REQUIRED_PAYLOAD_INDEXES["literature"]:
        storage.client.create_payload_index(storage.collection, field, field_schema=PayloadSchemaType.KEYWORD, wait=True)
    source_filter = Filter(must=[FieldCondition(key="source", match=MatchValue(value=entry.source))])
    before = storage.client.count(storage.collection, count_filter=source_filter, exact=True).count
    # Delete first: the new extraction can yield fewer chunks than the old,
    # and leftover old ids would otherwise stay retrievable.
    storage.client.delete(storage.collection, points_selector=FilterSelector(filter=source_filter), wait=True)
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{entry.source}:{i}")) for i in range(len(chunks))]
    tags = entry.payload()
    storage.upsert(ids, vectors, [{**tags, "text": text} for text in chunks])
    after = storage.client.count(storage.collection, count_filter=source_filter, exact=True).count
    print(f"{entry.source}: replaced {before} chunks with {after}")
    print("Next: scripts.clear_shared_answers and scripts.refresh_rule_justifications (local and production).")


if __name__ == "__main__":
    main()
