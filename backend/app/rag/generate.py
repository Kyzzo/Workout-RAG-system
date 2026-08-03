from typing import Literal

import pydantic
from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter, MatchValue

from .data_loader import embed_texts
from .qdrant_storage import QdrantStorage

client = OpenAI()

GroundingLevel = Literal["fully_grounded", "blended", "general_knowledge"]


def _build_volume_response_schema(chunk_ids: list[str]) -> type[pydantic.BaseModel]:
    # chunk_ids is constrained to an enum of THIS call's retrieved IDs so the
    # model can't self-report a citation that was never actually retrieved
    # (citation_verification.txt section 2 - structural prevention, not a
    # post-hoc check). Falls back to a plain str list if nothing was
    # retrieved at all, since Literal[] with zero options is invalid.
    chunk_id_type = Literal[tuple(chunk_ids)] if chunk_ids else str
    return pydantic.create_model(
        "VolumeFields",
        sets=(int, ...),
        chunk_ids=(list[chunk_id_type], ...),
        grounding=(GroundingLevel, ...),
    )


def generate_volume_sets(muscle_group: str, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
    query = build_volume_query(muscle_group, goal)
    query_vector = embed_texts([query])[0]

    category_filter = Filter(
        must=[FieldCondition(key="category", match=MatchValue(value="volume"))]
    )
    chunks = QdrantStorage(collection="literature").search(
        query_vector, top_k=5, query_filter=category_filter
    )

    context_block = "\n\n".join(f"[{c['id']}] {c['text']}" for c in chunks)
    response_schema = _build_volume_response_schema([c["id"] for c in chunks])

    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You answer using only the provided research context. "
                "If the context doesn't support a confident answer, make your best "
                "estimate from what's given rather than using outside knowledge. "
                "Each context chunk is labeled with a bracketed ID like [abc-123]. "
                "In chunk_ids, list the IDs of the chunks that actually informed "
                "your answer - do not invent an ID that isn't shown above. Set "
                "grounding to 'fully_grounded' if the cited chunks fully account "
                "for your answer, 'blended' if you combined them with general "
                "knowledge, or 'general_knowledge' if no provided chunk "
                "meaningfully supports your answer (in which case chunk_ids "
                "should be empty).",
            },
            {
                "role": "user",
                "content": f"Context:\n{context_block}\n\nQuestion: {query}",
            },
        ],
        response_format=response_schema,
    )

    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Model refused to generate: {message.refusal}")
    return message.parsed, chunks

#current idea, used to get a set per week number but caller will get api answer and reference against other
#excercises within same muscle group
#other consideration potentially is excercises that hit multiple muscle groups (count fractional sets?)
def build_volume_query(muscle_group: str, goal: str) -> str:
    return (
        f"What is the optimal weekly training volume (number of sets) "
        f"for {muscle_group} to support a training goal of {goal}?"
    )
