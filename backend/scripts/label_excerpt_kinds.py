"""
Label stored excerpts with their kind (app/rag/excerpt_kinds.py) in place -
no re-embedding. New ingests are labeled as they're stored; this backfills
the corpus, and re-labels it after a change to the labeling prompt or model.
Only excerpts without a kind are labeled unless --relabel is given.

One cheap model call per excerpt (the 632 body excerpts cost well under a
dollar on gpt-5-mini); reference-list excerpts are 'bibliography' with no
call. Labels are saved to a file first, so they can be reviewed - value
generation stops retrieving excerpts labeled as reporting no result - and
applied without paying for them again.

Qdrant is shared by local and production, so applying changes what the live
app retrieves immediately (once the backend reads `kind`). --clear undoes it.

Usage (from backend/):
    uv run python -m scripts.label_excerpt_kinds --dry-run          # label, save, write nothing
    uv run python -m scripts.label_excerpt_kinds --apply FILE       # write saved labels
    uv run python -m scripts.label_excerpt_kinds                    # label and write
    uv run python -m scripts.label_excerpt_kinds --relabel          # also re-label labeled excerpts
    uv run python -m scripts.label_excerpt_kinds --clear            # remove every kind
Then: scripts.clear_shared_answers and scripts.refresh_rule_justifications
(local and production).
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from qdrant_client.models import PayloadSchemaType

from app.rag.excerpt_kinds import NON_FINDING_KINDS, add_kinds
from app.rag.qdrant_storage import QdrantStorage


def _stored(client, collection) -> list:
    points, offset = [], None
    while True:
        batch, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=["text", "section", "citation", "source", "kind"],
        )
        points += batch
        if offset is None:
            return points


def _label(points) -> list[dict]:
    # One paper at a time, each paper's excerpts labeled in parallel.
    by_source = defaultdict(list)
    for point in points:
        by_source[point.payload.get("source")].append(point)
    labels = []
    for source, group in by_source.items():
        payloads = [dict(p.payload) for p in group]
        add_kinds(payloads[0].get("citation") or source, payloads)
        print(f"  {source}: {dict(Counter(p.get('kind', 'UNLABELED') for p in payloads))}")
        labels += [
            {"id": str(point.id), "source": source, "section": payload.get("section"),
             "kind": payload.get("kind"), "text": payload["text"]}
            for point, payload in zip(group, payloads)
        ]
    return labels


def _apply(client, collection, labels: list[dict]):
    client.create_payload_index(collection, "kind", field_schema=PayloadSchemaType.KEYWORD, wait=True)
    ids_by_kind = defaultdict(list)
    for label in labels:
        if label["kind"] is not None:
            ids_by_kind[label["kind"]].append(label["id"])
    for kind, ids in ids_by_kind.items():
        client.set_payload(collection, payload={"kind": kind}, points=ids, wait=True)
    print(f"wrote kind on {sum(len(ids) for ids in ids_by_kind.values())} excerpts")


def main():
    parser = argparse.ArgumentParser(description="Label stored excerpts with their kind")
    parser.add_argument("--dry-run", action="store_true", help="label and save, write nothing to Qdrant")
    parser.add_argument("--relabel", action="store_true", help="also re-label excerpts that have a kind")
    parser.add_argument("--apply", metavar="FILE", help="write labels saved by an earlier run, no model calls")
    parser.add_argument("--clear", action="store_true", help="remove `kind` from every excerpt")
    parser.add_argument("--out", default="excerpt_kinds.json", help="where to save the labels")
    args = parser.parse_args()

    storage = QdrantStorage(collection="literature")
    client, collection = storage.client, storage.collection
    if args.clear:
        ids = [p.id for p in _stored(client, collection) if "kind" in p.payload]
        if ids:
            client.delete_payload(collection, keys=["kind"], points=ids, wait=True)
        print(f"removed kind from {len(ids)} excerpts")
        return
    if args.apply:
        _apply(client, collection, json.loads(Path(args.apply).read_text(encoding="utf-8")))
        return

    points = [p for p in _stored(client, collection) if args.relabel or "kind" not in p.payload]
    print(f"{len(points)} excerpts to label")
    if not points:
        return
    labels = _label(points)
    Path(args.out).write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total: {dict(Counter(label['kind'] or 'UNLABELED' for label in labels))}")
    no_result = [l for l in labels if l["kind"] in NON_FINDING_KINDS and l["section"] != "references"]
    print(f"{len(no_result)} body excerpts labeled as reporting no result; all labels saved to {args.out}")
    if args.dry_run:
        print(f"dry run: nothing written. Review, then: --apply {args.out}")
        return
    _apply(client, collection, labels)


if __name__ == "__main__":
    main()
