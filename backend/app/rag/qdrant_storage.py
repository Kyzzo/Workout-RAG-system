import hashlib
import os
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, FieldCondition, Filter, MatchValue, PayloadSchemaType, PointStruct, VectorParams,
)

load_dotenv()

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ["QDRANT_API_KEY"]

# Which deployment this is. Local and production have separate Postgres
# databases (each numbering users from 1) but share this Qdrant cluster, so
# anything per-user stored here is tagged with the environment and the
# user's Clerk ID - never the Postgres user id, which means a different
# person in each environment. Railway sets RAILWAY_ENVIRONMENT_NAME.
ENVIRONMENT = os.getenv("RAILWAY_ENVIRONMENT_NAME", "local")

# Qdrant Cloud's strict mode refuses to filter on a payload field at all
# unless it has an index — each collection needs the fields its retrieval
# filtering actually depends on: "literature" filters by research
# categories, outcome, paper (source) and section (to leave bibliographies
# out) and kind (value generation retrieves only excerpts reporting a
# result - rag/excerpt_kinds.py); "user_context" (users' own documents) by
# environment + owner (the privacy boundary: owner is the Clerk user id) and
# document (to delete one document's excerpts).
REQUIRED_PAYLOAD_INDEXES = {
    "literature": ("categories", "outcome", "source", "section", "kind"),
    "user_context": ("environment", "owner", "document_id"),
}

# Paper-level tags stored on every excerpt (corpus/papers.json), plus the
# excerpt's section ('body' or 'references') and kind (rag/excerpt_kinds.py),
# both set at ingestion.
_TAG_FIELDS = (
    "categories", "citation", "study_type", "outcome", "population", "year", "publication", "evidence_note",
    "section", "kind",
)

# Reference lists name the very topics a question asks about, so they match
# well but state no findings - and in per-paper search they took a paper's
# few slots (Lopez 2021's best match for a rep-range question was its
# bibliography). Excluded in the search itself, so they never take a slot.
_IS_REFERENCES = FieldCondition(key="section", match=MatchValue(value="references"))


def _without_references(query_filter: Filter | None) -> Filter:
    if query_filter is None:
        return Filter(must_not=[_IS_REFERENCES])
    return query_filter.model_copy(update={"must_not": [*(query_filter.must_not or []), _IS_REFERENCES]})


def chunk_point_id(source: str, index: int, text: str) -> str:
    """A chunk's Qdrant point id. Citations are stored by point id and reused
    when a chunk is retrieved again, so the id includes the text: re-chunking
    a paper (a loader change shifts every index) must not hand an old
    citation's id - and the excerpt it showed - to different text."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}:{index}:{digest}"))


def _to_chunks(results) -> list[dict]:
    chunks = []
    for r in results:
        payload = getattr(r, "payload", None) or {}
        text = payload.get("text", "")
        if text:
            chunks.append({
                "id": str(r.id), "text": text, "source": payload.get("source", ""),
                "category": payload.get("category"), "score": getattr(r, "score", 0.0),
                **{field: payload[field] for field in _TAG_FIELDS if field in payload},
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
            for index_field in REQUIRED_PAYLOAD_INDEXES.get(collection, ()):
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

    def _filter(self, query_filter: Filter | None) -> Filter | None:
        return _without_references(query_filter) if self.collection == "literature" else query_filter

    def search(self, query_vector: list[float], top_k: int = 5, query_filter: Filter | None = None):
        results = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=self._filter(query_filter),
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
            query_filter=self._filter(query_filter),
            limit=sources,
            group_size=per_source,
            with_payload=True,
        ).groups
        chunks = _to_chunks([hit for group in groups for hit in group.hits])
        return sorted(chunks, key=lambda c: c["score"], reverse=True)
