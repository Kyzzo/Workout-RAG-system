from typing import Literal

import pydantic
from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter, MatchValue

from .data_loader import embed_texts
from .qdrant_storage import QdrantStorage

client = OpenAI()

GroundingLevel = Literal["fully_grounded", "blended", "general_knowledge"]

_GENERATION_SYSTEM_PROMPT = (
    "You answer using only the provided research context. "
    "If the context doesn't support a confident answer, make your best "
    "estimate from what's given rather than using outside knowledge. "
    "Give the requested value as a single, concise value (e.g. '70% 1RM', "
    "'RPE 8', '8-10') - not a sentence or paragraph explaining it. "
    "Each context chunk is labeled with a bracketed ID like [abc-123]. "
    "In chunk_ids, list the IDs of the chunks that actually informed "
    "your answer - do not invent an ID that isn't shown above. Set "
    "grounding to 'fully_grounded' if the cited chunks fully account "
    "for your answer, 'blended' if you combined them with general "
    "knowledge, or 'general_knowledge' if no provided chunk "
    "meaningfully supports your answer (in which case chunk_ids "
    "should be empty)."
)


def _build_response_schema(
    field_name: str, field_type: type, field_description: str | None, chunk_ids: list[str]
) -> type[pydantic.BaseModel]:
    # chunk_ids is constrained to an enum of THIS call's retrieved IDs so the
    # model can't self-report a citation that was never actually retrieved
    # (citation_verification.txt section 2 - structural prevention, not a
    # post-hoc check). Falls back to a plain str list if nothing was
    # retrieved at all, since Literal[] with zero options is invalid.
    chunk_id_type = Literal[tuple(chunk_ids)] if chunk_ids else str
    field_spec = (field_type, pydantic.Field(description=field_description)) if field_description else (field_type, ...)
    return pydantic.create_model(
        "GeneratedField",
        **{field_name: field_spec},
        chunk_ids=(list[chunk_id_type], ...),
        grounding=(GroundingLevel, ...),
    )


def _generate_field(
    field_name: str,
    field_type: type,
    category: str,
    query: str,
    field_description: str | None = None,
) -> tuple[pydantic.BaseModel, list[dict]]:
    query_vector = embed_texts([query])[0]

    category_filter = Filter(
        must=[FieldCondition(key="category", match=MatchValue(value=category))]
    )
    chunks = QdrantStorage(collection="literature").search(
        query_vector, top_k=5, query_filter=category_filter
    )

    context_block = "\n\n".join(f"[{c['id']}] {c['text']}" for c in chunks)
    response_schema = _build_response_schema(
        field_name, field_type, field_description, [c["id"] for c in chunks]
    )

    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _GENERATION_SYSTEM_PROMPT},
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


def generate_volume_sets(muscle_group: str, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field("sets", int, "volume", build_volume_query(muscle_group, goal))


def generate_intensity_load(muscle_group: str, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field(
        "load",
        str,
        "intensity",
        build_intensity_query(muscle_group, goal),
        field_description="Training load as a percentage of 1RM (e.g. '70% 1RM') "
        "or an RPE value (e.g. 'RPE 8') - never a rep range or rep count.",
    )


def generate_frequency(muscle_group: str, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field(
        "frequency",
        int,
        "frequency",
        build_frequency_query(muscle_group, goal),
        field_description="Training frequency as a single integer - sessions "
        "per week for this muscle group.",
    )

#current idea, used to get a set per week number but caller will get api answer and reference against other
#excercises within same muscle group
#other consideration potentially is excercises that hit multiple muscle groups (count fractional sets?)
def build_volume_query(muscle_group: str, goal: str) -> str:
    return (
        f"What is the optimal weekly training volume (number of sets) "
        f"for {muscle_group} to support a training goal of {goal}?"
    )


def build_intensity_query(muscle_group: str, goal: str) -> str:
    return (
        f"What training load is recommended for {muscle_group} to support "
        f"a training goal of {goal}? Answer with the load ITSELF - a "
        f"percentage of 1RM (e.g. '70% 1RM') or an RPE value (e.g. 'RPE 8') "
        f"- not a rep range or rep count, even if the source material "
        f"discusses reps and load together."
    )


def build_frequency_query(muscle_group: str, goal: str) -> str:
    return (
        f"How many times per week should {muscle_group} be trained to "
        f"support a training goal of {goal}? Answer with a single whole "
        f"number of sessions per week - if the source material gives a "
        f"range, pick the single most defensible value within it."
    )


ProgressionSchemeType = Literal["linear", "undulating"]


def generate_progression_scheme(muscle_group: str, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field(
        "scheme",
        ProgressionSchemeType,
        "progression",
        build_progression_query(muscle_group, goal),
        field_description="Which periodization model is recommended: "
        "'linear' (progressively increasing intensity/decreasing volume "
        "across the block) or 'undulating' (intensity/volume varies "
        "week to week or day to day rather than trending in one direction).",
    )


def build_progression_query(muscle_group: str, goal: str) -> str:
    return (
        f"For a strength training goal, is linear or undulating "
        f"periodization recommended for {muscle_group} across a training "
        f"block? Answer with which scheme is recommended, not a description "
        f"of both."
    )
