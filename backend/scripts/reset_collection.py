"""
Delete and recreate a Qdrant collection — wipes all ingested points.

Use when the payload SHAPE is changing (e.g. adding a subcategory field)
and you'd rather re-ingest everything fresh than backfill old points.

Usage:
    uv run python -m scripts.reset_collection <collection_name>
"""

import argparse

from app.rag.qdrant_storage import QDRANT_API_KEY, QDRANT_URL, QdrantStorage
from qdrant_client import QdrantClient


def main():
    parser = argparse.ArgumentParser(description="Wipe a Qdrant collection")
    parser.add_argument("collection", choices=["literature", "user_context"])
    args = parser.parse_args()

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)

    confirm = input(f"This will permanently delete ALL points in '{args.collection}'. Type the collection name to confirm: ")
    if confirm != args.collection:
        print("Confirmation didn't match — aborted, nothing was deleted.")
        return

    if client.collection_exists(args.collection):
        client.delete_collection(args.collection)
        print(f"Deleted collection '{args.collection}'.")
    else:
        print(f"Collection '{args.collection}' didn't exist — nothing to delete.")

    QdrantStorage(collection=args.collection)
    print(f"Recreated empty collection '{args.collection}'. Ready to re-ingest.")


if __name__ == "__main__":
    main()
