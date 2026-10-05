"""
Write corpus/papers.json's tags onto every stored excerpt in place - no
re-embedding, no PDF processing. Run after editing tags or adding a paper's
manifest entry. Also merges duplicate ingests: for an entry with
`merged_from`, one stored copy is renamed to the entry's source id and the
other copies are deleted.

Qdrant is shared by local and production, so this changes what the live
app retrieves immediately. It keeps the old single `category` field
alongside `categories`, so a backend that predates the manifest keeps
working until it's redeployed.

Usage (from backend/):
    uv run python -m scripts.apply_paper_metadata --dry-run
    uv run python -m scripts.apply_paper_metadata
Then: scripts.clear_shared_answers and scripts.refresh_rule_justifications
(local and production).
"""

import argparse
from collections import Counter

from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PayloadSchemaType

from app.rag.corpus import load_manifest
from app.rag.qdrant_storage import REQUIRED_PAYLOAD_INDEXES, QdrantStorage


def _source_filter(source: str) -> Filter:
    return Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))])


def _stored_counts(client, collection) -> Counter:
    counts, offset = Counter(), None
    while True:
        points, offset = client.scroll(collection, limit=256, offset=offset, with_payload=["source"])
        counts.update(p.payload.get("source") for p in points)
        if offset is None:
            return counts


def main():
    parser = argparse.ArgumentParser(description="Apply corpus/papers.json tags to stored excerpts")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = parser.parse_args()

    storage = QdrantStorage(collection="literature")
    client, collection = storage.client, storage.collection
    manifest = load_manifest()
    counts = _stored_counts(client, collection)
    act = not args.dry_run
    if act:
        for field in REQUIRED_PAYLOAD_INDEXES["literature"]:
            client.create_payload_index(collection, field, field_schema=PayloadSchemaType.KEYWORD, wait=True)

    for paper in manifest.values():
        # Merge duplicate ingests of the same paper into one stored copy.
        if paper.merged_from:
            copies = [s for s in paper.merged_from if counts.get(s)]
            keep = paper.source if counts.get(paper.source) else (copies[0] if copies else None)
            if keep and keep != paper.source:
                print(f"rename   {keep} ({counts[keep]} chunks) -> {paper.source}")
                if act:
                    client.set_payload(collection, {"source": paper.source}, points=_source_filter(keep), wait=True)
                counts[paper.source] += counts.pop(keep)
            for duplicate in (s for s in copies if s not in (keep, paper.source)):
                print(f"delete   {duplicate} ({counts[duplicate]} chunks, duplicate of {paper.source})")
                if act:
                    client.delete(collection, points_selector=FilterSelector(filter=_source_filter(duplicate)), wait=True)
                counts.pop(duplicate)

        if not counts.get(paper.source):
            print(f"MISSING  {paper.source}: in the manifest but not stored - ingest it")
            continue
        print(f"tag      {paper.source} ({counts[paper.source]} chunks): {', '.join(paper.categories)} · "
              f"{paper.study_type} · {paper.outcome} · {paper.population} · {paper.year} · {paper.publication}")
        if act:
            client.set_payload(collection, paper.payload(), points=_source_filter(paper.source), wait=True)

    for source in sorted(set(counts) - set(manifest)):
        print(f"UNLISTED {source} ({counts[source]} chunks): stored but not in the manifest - add it or delete it")
    print("\n(dry run - nothing written)" if args.dry_run else "\ndone")


if __name__ == "__main__":
    main()
