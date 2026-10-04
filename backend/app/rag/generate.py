from dataclasses import dataclass
from typing import Literal

import pydantic
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client.models import FieldCondition, Filter, MatchValue

from .data_loader import embed_texts
from .qdrant_storage import QdrantStorage

load_dotenv()

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
    "should be empty). If you're told what's already prescribed "
    "elsewhere in the program for the same muscle group this week, "
    "treat the research range as a budget for that muscle group as a "
    "whole, not a fresh allowance for this exercise alone - pick a value "
    "for THIS exercise such that the combined total across all of them "
    "stays within what the research supports."
)


@dataclass
class Adjustment:
    """A chat request to change an existing value rather than regenerate it.

    increase/decrease: generation is told the current value and the
    direction, and to return the current value unchanged if the research
    doesn't support moving that way (checked mechanically afterwards where
    possible - see routers/generation.py).
    set_value: a user override. The value field's type is locked to exactly
    the requested value, so the model can't substitute its own number - it
    can only report which retrieved chunks (if any) genuinely support it,
    and verification then checks those claims as usual.
    """

    kind: Literal["increase", "decrease", "set_value"]
    request: str
    current_value: int | str
    requested_value: int | str | None = None

    def instruction(self) -> str:
        if self.kind == "set_value":
            return (
                f"The user has chosen the value {self.requested_value!r} themselves "
                f'("{self.request}"). Your answer must be exactly that value. In '
                "chunk_ids, cite only chunks that genuinely support that specific "
                "value; if none do, report grounding as general_knowledge with no "
                "chunk_ids rather than citing something that doesn't support it."
            )
        direction = "higher" if self.kind == "increase" else "lower"
        return (
            f"The current prescribed value is {self.current_value!r}. The user asked "
            f'to make it {direction}: "{self.request}". Choose a value {direction} '
            f"than {self.current_value!r} that the research still supports. If the "
            f"research doesn't support going any {direction}, return "
            f"{self.current_value!r} unchanged."
        )

    def locked_type(self) -> type | None:
        return Literal[self.requested_value] if self.kind == "set_value" else None


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


def _retrieve_chunks(query: str, category: str | None) -> list[dict]:
    query_vector = embed_texts([query])[0]

    # category=None (general Q&A, not tied to one of the four dosage
    # categories) searches the whole literature corpus unfiltered, rather
    # than forcing an arbitrary category choice on a question that isn't
    # actually about a single prescribed parameter.
    category_filter = (
        Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
        if category is not None
        else None
    )
    return QdrantStorage(collection="literature").search(
        query_vector, top_k=5, query_filter=category_filter
    )


def _generate_field(
    field_name: str,
    field_type: type,
    category: str | None,
    query: str,
    field_description: str | None = None,
    sibling_context: str | None = None,
    adjustment: Adjustment | None = None,
    guidance: str | None = None,
) -> tuple[pydantic.BaseModel, list[dict]]:
    chunks = _retrieve_chunks(query, category)

    context_block = "\n\n".join(f"[{c['id']}] {c['text']}" for c in chunks)
    locked_type = adjustment.locked_type() if adjustment else None
    response_schema = _build_response_schema(
        field_name, locked_type or field_type, field_description, [c["id"] for c in chunks]
    )

    user_content = f"Context:\n{context_block}\n\nQuestion: {query}"
    if sibling_context:
        # Passed as plain context, same standing as muscle_group/goal - NOT
        # a claim needing its own citation. The research chunk still backs
        # the range itself; this just tells the model where in that range
        # to land given what's already allocated elsewhere (the
        # cross-exercise volume-coherence problem in datamodel.txt).
        user_content += (
            "\n\nAlready prescribed this week for other exercises training "
            f"the same muscle group:\n{sibling_context}"
        )
    if adjustment:
        user_content += f"\n\nAdjustment: {adjustment.instruction()}"
    if guidance:
        user_content += f"\n\nUser preference: {guidance}"

    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _GENERATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format=response_schema,
    )

    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Model refused to generate: {message.refusal}")
    return message.parsed, chunks


# Most sets one exercise gets in one session. A convention, not a research
# claim: the literature reports WEEKLY volume per muscle, which then has to
# be spread across exercises and sessions - without a cap, a 2-day split
# with one chest exercise would put the whole weekly target (12 sets of
# bench) into a single session. Hypertrophy spreads a muscle's sets across
# several exercises (systematic exercise variation - see Kassiano et al.
# 2022) rather than piling them on one; strength allows 5 for 5x5-style
# main lifts.
_MAX_SETS_PER_EXERCISE = {"hypertrophy": 3, "strength": 5}


def max_sets_per_exercise(goal: str) -> int:
    return _MAX_SETS_PER_EXERCISE.get(goal, 4)


VolumePreference = Literal["minimal", "moderate", "high"]

# Where to land inside the range the research supports. Not a different
# claim: every option must still be a value the cited excerpts support, and
# verification checks it the same way - a preference picks a point in the
# supported range, it doesn't widen the range.
_VOLUME_GUIDANCE = {
    "minimal": "a minimal-effective-dose approach (fewer, harder sets). Choose the "
    "LOWEST weekly set count the provided research still reports as effective, "
    "not the optimum.",
    "moderate": None,
    "high": "a high-volume approach. Choose toward the HIGH end of the weekly set "
    "range the provided research supports, where it still reports added benefit.",
}
_RIR_GUIDANCE = {
    "minimal": "a low-volume approach that relies on effort: choose the closest-to-"
    "failure option the provided research supports.",
}


def generate_weekly_volume(
    muscle_group: str, goal: str, preference: str = "moderate",
) -> tuple[pydantic.BaseModel, list[dict]]:
    # The claim the volume research actually makes - weekly sets for the
    # muscle - so verification compares like with like (the mechanical
    # range check reads ranges like "10-20 sets" straight from the excerpt).
    return _generate_field(
        "weekly_sets", int, "volume", build_volume_query(muscle_group, goal),
        field_description="Total sets per WEEK for this muscle, across all of its "
        "exercises and sessions combined.",
        guidance=_VOLUME_GUIDANCE.get(preference),
    )


def generate_volume_sets(
    muscle_group: str, goal: str, sibling_context: str | None = None, adjustment: Adjustment | None = None
) -> tuple[pydantic.BaseModel, list[dict]]:
    # One exercise's sets in one session - used for single-value edits (a
    # week's "gen sets", chat adjust). Limited to 1..cap by the schema; an
    # exact user override still locks its own value via the adjustment.
    cap = max_sets_per_exercise(goal)
    return _generate_field(
        "sets", Literal[tuple(range(1, cap + 1))], "volume", build_volume_query(muscle_group, goal),
        field_description=f"Sets for THIS exercise in ONE session (at most {cap}). The research "
        "gives weekly totals for the whole muscle; this exercise gets a share of that "
        "weekly budget, never the whole of it.",
        sibling_context=sibling_context, adjustment=adjustment,
    )


def generate_intensity_load(
    muscle_group: str, goal: str, sibling_context: str | None = None, adjustment: Adjustment | None = None
) -> tuple[pydantic.BaseModel, list[dict]]:
    # sibling_context accepted for call-signature symmetry with
    # generate_volume_sets (both are called through the same
    # _attempt_generation/_generate_and_persist path), but never populated
    # in practice today - load doesn't have volume's additive "shared
    # weekly budget" problem, so this is left unwired rather than passed
    # through for a benefit that hasn't been demonstrated to exist.
    return _generate_field(
        "load",
        str,
        "intensity",
        build_intensity_query(muscle_group, goal),
        field_description="Training load as a percentage of 1RM, e.g. '75% 1RM' - "
        "never a rep range, rep count, RPE or RIR (effort is prescribed separately).",
        adjustment=adjustment,
    )


# A fixed menu rather than free text, so every RIR value is one of a few
# comparable, readable options (and chat can tell "harder" from "easier").
RirOption = Literal["0 RIR (to failure)", "0-1 RIR", "1-2 RIR", "2-3 RIR", "3-4 RIR"]


def generate_reps(
    muscle_group: str, goal: str, exercise_name: str,
    sibling_context: str | None = None, adjustment: Adjustment | None = None,
) -> tuple[pydantic.BaseModel, list[dict]]:
    # The repetition-continuum research (schoenfeld-etal-2021) is tagged
    # "intensity" - rep range and load are two sides of the same variable.
    return _generate_field(
        "reps", str, "intensity", build_reps_query(muscle_group, goal, exercise_name),
        field_description="A rep range per set, e.g. '6-10' or '8-12' - numbers only, "
        "no load or effort.",
        adjustment=adjustment,
    )


def generate_rir(
    muscle_group: str, goal: str, exercise_name: str,
    sibling_context: str | None = None, adjustment: Adjustment | None = None,
    preference: str = "moderate",
) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field(
        "rir", RirOption, "intensity", build_rir_query(muscle_group, goal, exercise_name),
        field_description="How many reps short of failure each set should end "
        "(reps in reserve); 0 RIR means taking the set to failure.",
        adjustment=adjustment,
        guidance=_RIR_GUIDANCE.get(preference),
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
        f"a training goal of {goal}? Answer with the load ITSELF as a "
        f"percentage of 1RM (e.g. '75% 1RM') - not a rep range or rep count, "
        f"even if the source material discusses reps and load together."
    )


def build_reps_query(muscle_group: str, goal: str, exercise_name: str) -> str:
    return (
        f"What repetition range per set is recommended for {exercise_name} "
        f"(training {muscle_group}) to support a training goal of {goal}? "
        f"Answer with a rep range like '8-12'."
    )


def build_rir_query(muscle_group: str, goal: str, exercise_name: str) -> str:
    return (
        f"How close to failure, in repetitions in reserve (RIR), should sets "
        f"of {exercise_name} (training {muscle_group}) be taken to support a "
        f"training goal of {goal}? 0 RIR means the set is taken to failure."
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


_QA_SYSTEM_PROMPT = (
    "You answer research questions using only the provided context. "
    "If the context doesn't fully answer the question, make your best "
    "estimate from what's given rather than using outside knowledge. "
    "Each context chunk is labeled with a bracketed ID like [abc-123]. "
    "Your answer can combine multiple chunks, but every entry in "
    "citations must name the SPECIFIC claim or sentence from your answer "
    "that chunk actually supports - not a summary of the whole answer, "
    "and not a paraphrase of the whole excerpt. Only cite a chunk for a "
    "claim it actually states or reports. In particular: a chunk stating "
    "what proportion of a dataset used some method (e.g. 'X% of studies "
    "trained to failure') describes the STUDIES INCLUDED in that "
    "research, not whether that method produces better results - only "
    "cite it for a claim about the dataset's composition itself, never "
    "for a claim about a method's effectiveness. Do not invent a chunk "
    "ID that isn't shown above. Set grounding to 'fully_grounded' if the "
    "cited chunks fully account for your answer, 'blended' if you "
    "combined them with general knowledge, or 'general_knowledge' if no "
    "provided chunk meaningfully supports your answer (in which case "
    "citations should be empty)."
)


def _build_qa_response_schema(chunk_ids: list[str]) -> type[pydantic.BaseModel]:
    # Deliberately NOT built on top of _build_response_schema's flat
    # chunk_ids: list[...] shape - a free-text answer can synthesize
    # several distinct claims from several chunks, and a flat list gives
    # verification nothing to check per chunk except the whole answer,
    # which is exactly how a real citation ended up backing a claim it
    # didn't make (a dataset-composition stat used to imply an efficacy
    # finding). Each citation names the specific claim it's FOR, so
    # per-chunk judge verification has something atomic to check, the
    # same granularity field-level generation already has.
    chunk_id_type = Literal[tuple(chunk_ids)] if chunk_ids else str
    cited_claim = pydantic.create_model(
        "CitedClaim",
        chunk_id=(chunk_id_type, ...),
        supports=(
            str,
            pydantic.Field(
                description="The specific claim or sentence from the answer "
                "this chunk is cited to support - not the whole answer."
            ),
        ),
    )
    return pydantic.create_model(
        "QAAnswer",
        answer=(str, ...),
        citations=(list[cited_claim], ...),
        grounding=(GroundingLevel, ...),
    )


def answer_general_question(topic: str) -> tuple[pydantic.BaseModel, list[dict]]:
    # General Q&A (Phase 6 chat mode 3, phase6_chat_routing_concepts.txt
    # section 4): not tied to a specific WeeklyPrescription-level field, so
    # category=None searches across the whole corpus rather than one of the
    # four dosage categories, and the answer is free text, not a typed value
    # meant to be persisted anywhere.
    chunks = _retrieve_chunks(topic, None)
    context_block = "\n\n".join(f"[{c['id']}] {c['text']}" for c in chunks)
    response_schema = _build_qa_response_schema([c["id"] for c in chunks])

    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _QA_SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion: {topic}"},
        ],
        response_format=response_schema,
    )

    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Model refused to generate: {message.refusal}")
    return message.parsed, chunks


_DISCUSSION_SYSTEM_PROMPT = (
    "You are answering a user's question about one specific, already-"
    "generated training prescription. Use only the prescription's current "
    "value and the provided supporting citation excerpts - don't invent new "
    "research, and don't second-guess or recompute what the value should "
    "be (that's a separate 'adjust' action, not this one). If the citations "
    "don't clearly answer the question, say so honestly rather than "
    "guessing. Give a concise, direct answer, not a restatement of the raw "
    "prescription data."
)


def answer_prescription_discussion(question: str, prescription_summary: str, citation_snippets: list[str]) -> str:
    # No new retrieval or citation-verification here - this only rephrases
    # ALREADY-verified, ALREADY-stored citation text into a direct answer to
    # the user's actual question (phase6_chat_routing_concepts.txt section
    # 4's "zero marginal cost for the citation-CHECKING part" - checking,
    # not the whole response, which still needs an LLM call to actually
    # engage with what was asked instead of just echoing stored data back).
    citations_block = "\n\n".join(citation_snippets) if citation_snippets else "(no verified supporting citations on file)"
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _DISCUSSION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Current prescription: {prescription_summary}\n\n"
                f"Supporting citations:\n{citations_block}\n\nQuestion: {question}",
            },
        ],
    )
    return completion.choices[0].message.content
