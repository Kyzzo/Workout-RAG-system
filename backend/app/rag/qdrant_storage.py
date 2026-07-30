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

        contexts = []
        sources = set()
        for r in results:
            payload = getattr(r, "payload", None) or {}
            text = payload.get("text", "")
            source = payload.get("source", "")
            if text:
                contexts.append(text)
                sources.add(source)

        return {"contexts": contexts, "sources": list(sources)}
