import os

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, PayloadSchemaType, PointStruct, VectorParams

load_dotenv()

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ["QDRANT_API_KEY"]

# Qdrant Cloud's strict mode refuses to filter on a payload field at all
# unless it has an index — each collection needs the field its retrieval
# filtering actually depends on: "literature" filters by research category,
# "user_context" will filter by user_id (the privacy boundary).
REQUIRED_PAYLOAD_INDEXES = {
    "literature": "category",
    "user_context": "user_id",
}


def _to_chunks(results) -> list[dict]:
    chunks = []
    for r in results:
        payload = getattr(r, "payload", None) or {}
        text = payload.get("text", "")
        if text:
            chunks.append({
                "id": str(r.id), "text": text, "source": payload.get("source", ""),
                "category": payload.get("category"), "score": getattr(r, "score", 0.0),
            })
    return chunks


class QdrantStorage:
    def __init__(self, collection: str, dim: int = 3072):
        self.client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)
        self.collection = collection
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            index_field = REQUIRED_PAYLOAD_INDEXES.get(collection)
            if index_field:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=index_field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )

    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]):
        points = [
            PointStruct(id=ids[i], vector=vectors[i], payload=payloads[i])
            for i in range(len(ids))
        ]
        self.client.upsert(self.collection, points=points)

    def search(self, query_vector: list[float], top_k: int = 5, query_filter: Filter | None = None):
        results = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            with_payload=True,
            limit=top_k,
        ).points
        return _to_chunks(results)

    def search_per_source(
        self, query_vector: list[float], per_source: int, sources: int, query_filter: Filter | None = None,
    ):
        """The best `per_source` chunks from each of up to `sources` papers,
        best first - so every paper reaches the reranker even when one paper's
        wording dominates plain similarity search. Needs the `source` payload
        index (created by scripts/reingest_literature.py)."""
        groups = self.client.query_points_groups(
            collection_name=self.collection,
            query=query_vector,
            group_by="source",
            query_filter=query_filter,
            limit=sources,
            group_size=per_source,
            with_payload=True,
        ).groups
        chunks = _to_chunks([hit for group in groups for hit in group.hits])
        return sorted(chunks, key=lambda c: c["score"], reverse=True)
