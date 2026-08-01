import pydantic
from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter, MatchValue

from .data_loader import embed_texts
from .qdrant_storage import QdrantStorage

client = OpenAI()


class VolumeFields(pydantic.BaseModel):
    sets: int


def generate_volume_sets(muscle_group: str, goal: str) -> VolumeFields:
    query = build_volume_query(muscle_group, goal)
    query_vector = embed_texts([query])[0]

    category_filter = Filter(
        must=[FieldCondition(key="category", match=MatchValue(value="volume"))]
    )
    results = QdrantStorage(collection="literature").search(
        query_vector, top_k=5, query_filter=category_filter
    )

    context_block = "\n\n".join(f"- {c}" for c in results["contexts"])
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You answer using only the provided research context. "
                "If the context doesn't support a confident answer, make your best "
                "estimate from what's given rather than using outside knowledge.",
            },
            {
                "role": "user",
                "content": f"Context:\n{context_block}\n\nQuestion: {query}",
            },
        ],
        response_format=VolumeFields,
    )

    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Model refused to generate: {message.refusal}")
    return message.parsed

#current idea, used to get a set per week number but caller will get api answer and reference against other
#excercises within same muscle group
#other consideration potentially is excercises that hit multiple muscle groups (count fractional sets?)
def build_volume_query(muscle_group: str, goal: str) -> str:
    return (
        f"What is the optimal weekly training volume (number of sets) "
        f"for {muscle_group} to support a training goal of {goal}?"
    )
