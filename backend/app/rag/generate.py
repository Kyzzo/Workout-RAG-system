import logging
import re
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
logger = logging.getLogger(__name__)

GroundingLevel = Literal["fully_grounded", "blended", "general_knowledge"]

_GENERATION_SYSTEM_PROMPT = (
    "You answer using only the provided research context. "
    "If the context doesn't support a confident answer, make your best "
    "estimate from what's given rather than using outside knowledge. "
    "Give the requested value as a single, concise value (e.g. '70% 1RM', "
    "'RPE 8', '8-10') - not a sentence or paragraph explaining it. "
    "Each context chunk is labeled with a bracketed ID like [abc-123] "
    "and its paper. Base the value on findings for the outcome the "
    "question asks about: a strength finding never sets a hypertrophy "
    "value, or the reverse. Weigh the evidence: when meta-analyses or "
    "reviews are present, base the value on their pooled findings and "
    "treat single studies as supporting detail, not the deciding source. "
    "Keep each finding's meaning - 'no detectable superiority beyond X' "
    "or 'similar results across A-B' don't make X or any point in A-B an "
    "optimum to aim for. In chunk_ids, list EVERY chunk whose findings "
    "support your value (usually several, from different papers) and no "
    "chunk that doesn't - each one is checked, and a chunk that doesn't "
    "support the value as written is rejected. Do not invent an ID that "
    "isn't shown above. Set "
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


# Retrieval settings. Tuned for today's corpus (1-7 papers per category);
# raise them as categories grow toward 20-30 papers (target then: ~40
# candidates -> 10-12 kept for generation, ~60-80 -> 15-20 for chat, still
# max 2 per paper) and check each change with scripts/eval_retrieval.py.
# Generation runs dozens of field calls per block, many in parallel, so its
# count also bounds prompt tokens against the account's rate limit.
GENERATION_TOP_K = 10
GENERATION_CANDIDATES = 40
GENERAL_TOP_K = 15
GENERAL_CANDIDATES = 60
# Plus the best few chunks from EACH paper, so a paper whose wording is far
# from the question still reaches the reranker (the RIR meta-analyses never
# made a top-40 dominated by three papers).
CANDIDATES_PER_PAPER = 3
MAX_PAPERS = 40
# Per paper before backfilling. Without a cap one paper fills most slots
# (weekly volume got 3 of 5 excerpts from one 8-week study and none from the
# Pelland 2025 meta-analysis); but it's a preference, not a limit, since a
# category with one or two papers would otherwise get fewer excerpts.
MAX_CHUNKS_PER_PAPER = 2

# A question clearly about one dosage category searches it first.
_CATEGORY_KEYWORDS = {
    "volume": re.compile(r"\b(sets?|volume)\b", re.I),
    "intensity": re.compile(r"\b(rir|rpe|failure|intensity|load|reps?|1rm|heavy|light)\b", re.I),
    "frequency": re.compile(r"\b(frequency|how often|times (a|per) week|sessions? (a|per) week)\b", re.I),
    "progression": re.compile(r"\b(progress\w*|periodi[sz]\w*|deload\w*)\b", re.I),
    "recovery": re.compile(
        r"\b(damage|soreness|doms|recover\w*|fatigue\w*|deload\w*|rest days?|overtrain\w*|sleep)\b", re.I,
    ),
}
# Journal-style entries ("2023;12(2):29-36") and DOIs: three or more in one
# chunk means it's a bibliography, which lists papers rather than findings.
_CITATION_ENTRY = re.compile(r"\b(?:19|20)\d{2}\s*;\s*\d+|\bdoi\b", re.I)


def _is_reference_list(text: str) -> bool:
    return len(_CITATION_ENTRY.findall(text)) >= 3


def _category_filter(category: str) -> Filter:
    return Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])


def _usable(ranked: list[dict]) -> list[dict]:
    """Drops duplicate excerpts (a paper ingested under two categories has
    identical chunks under different ids) and reference lists, keeping order."""
    usable, seen_text = [], set()
    for chunk in ranked:
        key = " ".join(chunk["text"].split())
        if key in seen_text or _is_reference_list(chunk["text"]):
            continue
        seen_text.add(key)
        usable.append(chunk)
    return usable


def _select_diverse(ranked: list[dict], top_k: int, max_per_paper: int = MAX_CHUNKS_PER_PAPER) -> list[dict]:
    """Best-first selection from ranked candidates: drops duplicates and
    reference lists, takes up to `max_per_paper` from each paper, then
    backfills any remaining slots with the next-best excerpts regardless of
    paper, so a small category isn't starved."""
    usable = _usable(ranked)

    chosen, per_paper = [], {}
    for chunk in usable:
        if per_paper.get(chunk["source"], 0) < max_per_paper:
            per_paper[chunk["source"]] = per_paper.get(chunk["source"], 0) + 1
            chosen.append(chunk)
            if len(chosen) == top_k:
                return chosen
    picked = {id(c) for c in chosen}
    backfill = [c for c in usable if id(c) not in picked][: top_k - len(chosen)]
    order = {id(c): i for i, c in enumerate(usable)}
    return sorted(chosen + backfill, key=lambda c: order[id(c)])


# Reranking. Similarity search ranks excerpts by how closely their WORDING
# matches the question, which buries findings written in statistics
# language: asked whether 3x a week beats 2x, it returned eight excerpts of
# the study titled "...Two Versus Three Days Per Week" and none of Pelland's
# meta-regression result ("the marginal slope ... between frequency and
# hypertrophy was 0.32%"). So similarity search only gathers candidates, and
# a cheap model scores how well each one answers the question. Not a
# research claim (every cited excerpt is still judged), so the cheap model
# is fine; if it fails, the similarity order is used.
# (model, reasoning effort). gpt-4o-mini scored a directly relevant finding
# ('no significant difference between failure and non-failure') as 0;
# gpt-4.1-mini scored it 6 in ~2.5s (gpt-5-mini similar but 4-15s).
RERANK_MODEL = ("gpt-4.1-mini", None)
RERANK_MIN_SCORE = 4  # below: same topic but no finding that bears on the question
_RERANK_PROMPT = (
    "You rank research excerpts by how well they answer a question, for a system that cites them as "
    "evidence. Score every excerpt from 0 to 10: 9-10 = reports a finding that directly answers the "
    "question, for the outcome it asks about (e.g. hypertrophy vs strength); 6-8 = reports findings "
    "that clearly inform the answer; 4-5 = related findings that only partly bear on it; 1-3 = same "
    "topic but no finding that answers it (introduction, methods, study aims, limitations, a finding "
    "for a different outcome); 0 = unrelated or a reference list. Judge what the excerpt reports, not "
    "how many words it shares with the question - a statistical result can answer the question "
    "directly. Score every excerpt once."
)


def _rerank(question: str, candidates: list[dict]) -> list[dict]:
    """Candidates ordered by the reranker's score (ties keep similarity
    order), each with a `rerank_score`. On any failure, returned unchanged."""
    if len(candidates) < 2:
        return candidates
    # One required field per excerpt, so structured output guarantees every
    # excerpt gets a score - a free-form list let the model score only a few
    # (the rest defaulted to 0 and were treated as irrelevant).
    schema = pydantic.create_model(
        "ExcerptScores", **{f"excerpt_{i}": (int, ...) for i in range(len(candidates))},
    )
    numbered = "\n\n".join(
        f"[{i}] ({c['source']}) {' '.join(c['text'].split())[:1500]}" for i, c in enumerate(candidates)
    )
    try:
        model, effort = RERANK_MODEL
        completion = client.chat.completions.parse(
            model=model,
            **({"reasoning_effort": effort} if effort else {"temperature": 0}),
            messages=[
                {"role": "system", "content": _RERANK_PROMPT},
                {"role": "user", "content": f"Question: {question}\n\nExcerpts:\n{numbered}"},
            ],
            response_format=schema,
        )
        parsed = completion.choices[0].message.parsed
        scores = {i: max(0, min(10, getattr(parsed, f"excerpt_{i}"))) for i in range(len(candidates))}
    except Exception:
        logger.warning("Reranking failed; using similarity order", exc_info=True)
        return candidates
    scored = [{**c, "rerank_score": scores[i]} for i, c in enumerate(candidates)]
    order = sorted(range(len(scored)), key=lambda i: (-scored[i]["rerank_score"], i))
    return [scored[i] for i in order]


def _select(question: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Rerank, then pick: excerpts that bear on the question first (spread
    across papers, max 2 per paper before backfill), and only if that leaves
    room, the best of the rest - so a weak excerpt from another paper never
    displaces a strong second one from the same paper."""
    reranked = _rerank(question, _usable(candidates))
    relevant = [c for c in reranked if c.get("rerank_score", RERANK_MIN_SCORE) >= RERANK_MIN_SCORE]
    chosen = _select_diverse(relevant, top_k)
    if len(chosen) < top_k:
        picked = {id(c) for c in chosen}
        chosen += [c for c in reranked if id(c) not in picked and c not in relevant][: top_k - len(chosen)]
    return chosen


def _retrieve_chunks(query: str, category: str | None) -> list[dict]:
    """A generated field's (or rule's) evidence: its category's excerpts
    (category=None searches the whole corpus), reranked and diversified."""
    query_vector = embed_texts([query])[0]
    storage = QdrantStorage(collection="literature")
    query_filter = _category_filter(category) if category is not None else None
    candidates = storage.search(query_vector, top_k=GENERATION_CANDIDATES, query_filter=query_filter)
    candidates += storage.search_per_source(
        query_vector, per_source=CANDIDATES_PER_PAPER, sources=MAX_PAPERS, query_filter=query_filter,
    )
    return _select(query, candidates, GENERATION_TOP_K)


def _retrieve_general_chunks(topic: str) -> list[dict]:
    """A chat question's evidence: candidates from the categories it names
    and from the whole corpus, reranked and diversified."""
    query_vector = embed_texts([topic])[0]
    storage = QdrantStorage(collection="literature")
    matched = [cat for cat, pattern in _CATEGORY_KEYWORDS.items() if pattern.search(topic)]
    ranked = []
    for category in matched:
        ranked += storage.search(query_vector, top_k=GENERAL_TOP_K, query_filter=_category_filter(category))
    ranked.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    ranked += storage.search(query_vector, top_k=GENERAL_CANDIDATES)
    ranked += storage.search_per_source(query_vector, per_source=CANDIDATES_PER_PAPER, sources=MAX_PAPERS)
    return _select(topic, ranked, GENERAL_TOP_K)


# The model that picks generated values, as (model, reasoning effort).
# Changing it (or any generation prompt or question)? Bump
# shared_answers.ANSWER_VERSION so stored answers are regenerated.
# Compared on weekly volume (4 muscles x 2 goals): gpt-4o-mini picked a 'no
# detectable superiority' point (31 sets) as a target and anchored on single
# studies; gpt-5 at minimal effort based values on the meta-analyses, cited
# 2-3 papers each and had every value verified, ~15s per value with judging.
GENERATION_MODEL = ("gpt-5", "minimal")


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

    context_block = "\n\n".join(f"[{c['id']}] ({c['source']}) {c['text']}" for c in chunks)
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

    model, effort = GENERATION_MODEL
    completion = client.chat.completions.parse(
        model=model,
        **({"reasoning_effort": effort} if effort else {}),
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

# Weekly sets per goal and volume preference, in fractional sets (the app's
# count), bound to Pelland et al. 2025's efficiency tiers so every option
# stays where added sets still pay off efficiently. The model picks the
# value within the band (schema-enforced) and cites it.
# - Hypertrophy (tiers: higher efficiency 5-10, intermediate 11-18): minimal
#   is the higher-efficiency tier, moderate and high split the intermediate.
# - Strength (tiers: minimum effective dose 1, higher efficiency 2,
#   intermediate 3-4; past that 'additional weekly sets do not consistently
#   enhance strength gains'): minimal 1-2, moderate 3, high 4 - capped at
#   the efficient tiers by product choice, like hypertrophy.
VOLUME_BANDS = {
    "hypertrophy": {"minimal": (5, 10), "moderate": (11, 14), "high": (15, 18)},
    "strength": {"minimal": (1, 2), "moderate": (3, 3), "high": (4, 4)},
}
_TIER_DESCRIPTIONS = {
    "hypertrophy": "higher efficiency 5-10, intermediate 11-18 fractional weekly sets",
    "strength": (
        "minimum effective dose 1, higher efficiency 2, intermediate 3-4 fractional weekly "
        "sets; beyond that, additional sets don't consistently enhance strength gains"
    ),
}


def _band_guidance(goal: str, preference: str) -> str:
    low, high = VOLUME_BANDS[goal][preference]
    target = f"{low} weekly sets" if low == high else f"between {low} and {high} weekly sets"
    return (
        f"a {preference}-volume approach: choose {target}, the part of the research's most "
        f"efficient range (Pelland et al. 2025's {goal} efficiency tiers: {_TIER_DESCRIPTIONS[goal]}) "
        f"that this preference covers. Pick the value in that band the provided research best "
        f"supports."
    )


_RIR_GUIDANCE = {
    "minimal": "a low-volume approach that relies on effort: choose the closest-to-"
    "failure option the provided research supports.",
}


def generate_weekly_volume(
    muscle_group: str | None, goal: str, preference: str = "moderate",
) -> tuple[pydantic.BaseModel, list[dict]]:
    # The claim the volume research actually makes - weekly sets for the
    # muscle - so verification compares like with like.
    low, high = VOLUME_BANDS[goal][preference]
    return _generate_field(
        "weekly_sets", Literal[tuple(range(low, high + 1))], "volume", build_volume_query(muscle_group, goal),
        field_description="Total sets per WEEK for this muscle, across all of its "
        "exercises and sessions combined. This app counts sets FRACTIONALLY: a set "
        "where the muscle is the main target counts as 1, a set where it's a "
        "secondary muscle counts as 0.5. If a source reports direct sets only, or "
        "fractional sets, keep that distinction in mind rather than treating them "
        "as the same number.",
        guidance=_band_guidance(goal, preference),
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
        "load", str, "intensity", build_intensity_query(muscle_group, goal),
        field_description=_LOAD_DESCRIPTION, adjustment=adjustment,
    )


_LOAD_DESCRIPTION = (
    "Training load as a percentage of 1RM, e.g. '75% 1RM' - never a rep range, rep count, "
    "RPE or RIR (effort is prescribed separately)."
)
_REPS_DESCRIPTION = "A rep range per set, e.g. '6-10' or '8-12' - numbers only, no load or effort."
_RIR_DESCRIPTION = (
    "How many reps short of failure each set should end (reps in reserve); 0 RIR means "
    "taking the set to failure."
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
        field_description=_REPS_DESCRIPTION, adjustment=adjustment,
    )


def generate_rir(
    muscle_group: str, goal: str, exercise_name: str,
    sibling_context: str | None = None, adjustment: Adjustment | None = None,
    preference: str = "moderate",
) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field(
        "rir", RirOption, "intensity", build_rir_query(muscle_group, goal, exercise_name),
        field_description=_RIR_DESCRIPTION, adjustment=adjustment,
        guidance=_RIR_GUIDANCE.get(preference),
    )


# Reps, RIR and load for a whole movement type rather than one named
# exercise: the research behind them (the repetition continuum, the
# proximity-to-failure meta-analyses) isn't exercise-specific, and asking
# per exercise mostly returned the same answer at far higher cost. The one
# distinction the research does draw is load - lighter loads need sets
# closer to failure - which compound vs. isolation stands in for. Used by
# whole-exercise generation (shared across programs, see
# app/shared_answers.py); chat adjustments still ask about the named
# exercise.
Movement = Literal["compound", "isolation"]
_MOVEMENT_PHRASE = {
    "compound": "compound (multi-joint) exercises such as squats, presses, rows and deadlifts",
    "isolation": "isolation (single-joint) exercises such as curls, lateral raises, leg extensions "
    "and calf raises",
}


def build_movement_query(field: str, goal: str, movement: str) -> str:
    exercises = _MOVEMENT_PHRASE[movement]
    if field == "reps":
        return (
            f"What repetition range per set is recommended for {exercises} to support a "
            f"training goal of {goal}? Answer with a rep range like '8-12'."
        )
    if field == "rir":
        return (
            f"How close to failure, in repetitions in reserve (RIR), should sets of {exercises} "
            f"be taken to support a training goal of {goal}? 0 RIR means the set is taken to failure."
        )
    if field == "load":
        return (
            f"What training load is recommended for {exercises} to support a training goal of "
            f"{goal}? Answer with the load ITSELF as a percentage of 1RM (e.g. '75% 1RM') - not a "
            f"rep range or rep count, even if the source material discusses reps and load together."
        )
    raise ValueError(f"No movement-level question for {field}")


def generate_for_movement(
    field: str, goal: str, movement: str, preference: str = "moderate",
) -> tuple[pydantic.BaseModel, list[dict]]:
    query = build_movement_query(field, goal, movement)
    if field == "reps":
        return _generate_field("reps", str, "intensity", query, field_description=_REPS_DESCRIPTION)
    if field == "rir":
        return _generate_field(
            "rir", RirOption, "intensity", query, field_description=_RIR_DESCRIPTION,
            guidance=_RIR_GUIDANCE.get(preference),
        )
    if field == "load":
        return _generate_field("load", str, "intensity", query, field_description=_LOAD_DESCRIPTION)
    raise ValueError(f"No movement-level generation for {field}")


def generate_frequency(muscle_group: str | None, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
    return _generate_field(
        "frequency",
        int,
        "frequency",
        build_frequency_query(muscle_group, goal),
        field_description="Training frequency as a single integer - sessions "
        "per week for this muscle group.",
    )

# muscle_group=None asks about any muscle: whole-block generation asks
# volume, frequency and progression once per goal (shared by every muscle,
# see app/shared_answers.py), since the meta-analyses behind them pool
# muscles rather than giving muscle-specific doses. Per-muscle wording is
# kept for single-value requests.
def build_volume_query(muscle_group: str | None, goal: str) -> str:
    # 'Supports as effective', not 'optimal': dosing research reports
    # effective ranges, tiers and diminishing returns, not one best number,
    # and the judge reads this question to decide what a value claims (incl.
    # the unit: this app counts fractional sets, as the meta-analyses do).
    return (
        f"How many sets per week for {muscle_group or 'each muscle'} does the research support "
        f"as an effective training volume for a goal of {goal}? Sets are "
        f"counted fractionally: a set where the muscle is only a secondary "
        f"mover counts as half a set."
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


def build_frequency_query(muscle_group: str | None, goal: str) -> str:
    return (
        f"How many times per week should {muscle_group or 'each muscle'} be trained to "
        f"support a training goal of {goal}? Answer with a single whole "
        f"number of sessions per week - if the source material gives a "
        f"range, pick the single most defensible value within it."
    )


ProgressionSchemeType = Literal["linear", "undulating"]


def generate_progression_scheme(muscle_group: str | None, goal: str) -> tuple[pydantic.BaseModel, list[dict]]:
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


def build_progression_query(muscle_group: str | None, goal: str) -> str:
    target = f"for {muscle_group} " if muscle_group else ""
    return (
        f"For a strength training goal, is linear or undulating "
        f"periodization recommended {target}across a training "
        f"block? Answer with which scheme is recommended, not a description "
        f"of both."
    )


# Rules shared by every free-text answer (chat Q&A and discussing a
# prescription). The answer is a list of single-claim statements, each
# naming its own sources, because every statement is verified separately
# and only statements with an accepted source are shown. That replaced an
# answer-plus-citations shape, where the prose AROUND the cited claims was
# never checked: a real answer merged a strength trend in direct sets
# (Aube 2022) with a hypertrophy threshold in fractional sets (Pelland via
# Remmert 2025) into a range neither study states.
_STATEMENT_RULES = (
    "Write your answer as a list of at most five statements - the "
    "findings that matter most for the question, not everything the "
    "excerpts contain. Each statement is ONE "
    "factual claim in one or two sentences, and its `sources` lists the "
    "IDs of the excerpts that state or report that exact claim. Every "
    "statement is checked against its sources and removed if they don't "
    "support it as written, so: do not write uncited statements, "
    "transitions or general knowledge as statements. Preserve each "
    "source's qualifiers exactly: the unit (e.g. 'fractional' sets vs "
    "direct sets, sets per week vs per session), the outcome (strength vs "
    "hypertrophy), the population and muscles studied, and the strength of "
    "the finding ('no detectable superiority beyond X', 'a trend toward'). "
    "Never upgrade a finding to 'optimal', 'best' or 'no benefit beyond'; "
    "'no detectable superiority beyond X' means the data couldn't show an "
    "advantage past X - state it that way, never as a limit, ceiling or "
    "maximum, even hedged with 'may be' or 'suggests'; and 'similar outcomes "
    "across A-B' never makes part of that range optimal. Use each source's "
    "exact figures. "
    "Within a statement, never combine figures from different excerpts, "
    "outcomes or units into a new range or number - report each source's "
    "figure separately, with its own context. Only write statements that "
    "bear on the question asked; a finding about a different outcome (e.g. "
    "strength when asked about hypertrophy) only if it's directly useful, "
    "and labeled as that outcome. A statement about what proportion of a dataset used "
    "some method describes the STUDIES INCLUDED, not whether the method "
    "works. Do not invent IDs. Set grounding to 'fully_grounded' if the "
    "cited excerpts fully account for the answer, 'blended' if you combined "
    "them with general knowledge, or 'general_knowledge' if no excerpt "
    "meaningfully supports an answer (then return no statements)."
)

_SUMMARY_RULES = (
    " Then write `summary`: the direct, practical answer to the question in "
    "two or three short, plain sentences, the way a knowledgeable coach "
    "would sum up the research for a lifter - e.g. a rough range the "
    "evidence generally supports, and what happens above or below it. No "
    "statistics or study jargon (no 'PUOS', 'SDES', confidence intervals); "
    "explain a term like 'fractional sets' in a few words if you use it. It is shown "
    "first, with the statements after it as the evidence. Its `sources` "
    "lists every excerpt it draws on. Unlike a statement, the summary may "
    "synthesize across excerpts, and it is checked against all of its "
    "sources together, so it must be a fair consensus of them: approximate "
    "or rounded figures and hedges ('roughly', 'most studies', 'for most "
    "lifters') are good; a range must be one the cited findings together "
    "actually cover; keep units (fractional vs direct sets), outcome and "
    "population; never call a sub-range optimal, or turn 'no detectable "
    "difference' into a ceiling or a proven benefit; and mention a real "
    "disagreement between sources rather than hide it. Set summary to null "
    "if the excerpts don't support a practical answer."
)

_QA_SYSTEM_PROMPT = (
    "You answer research questions using only the provided context. Each "
    "context excerpt is labeled with a bracketed ID like [abc-123]. "
    + _STATEMENT_RULES
    + _SUMMARY_RULES
)

_DISCUSSION_SYSTEM_PROMPT = (
    "You are answering a user's question about one specific, already-"
    "generated training prescription, using only its current values and the "
    "provided supporting excerpts - don't invent research, and don't second-"
    "guess or recompute what the value should be (that's a separate 'adjust' "
    "action). A statement that only describes the prescription's current "
    "values may cite the source ID 'prescription'. Each excerpt is labeled "
    "with the value it supports; never present an excerpt about one value "
    "(e.g. sets) as the reason for another (e.g. effort). If the excerpts "
    "don't answer the question, say so with no research statements rather "
    "than guessing. "
    + _STATEMENT_RULES
)


# The model that writes chat answers, as (model, reasoning effort). Tested
# on volume and failure questions: gpt-4o-mini wrote loose statements that
# the judge mostly removed (up to 4 of 5) and overstated findings; gpt-5 at
# minimal effort kept qualifiers, wrote plain summaries with rough ranges,
# and lost almost nothing to the judge (~45s per answer including judging;
# full effort took ~100s for no visible gain, gpt-5-mini kept study jargon).
STATEMENT_ANSWER_MODEL = ("gpt-5", "minimal")


def _statement_schema(source_ids: list[str], with_summary: bool = False) -> type[pydantic.BaseModel]:
    # Sources constrained to an enum of this call's actual excerpt IDs, the
    # same structural no-fabrication rule as field-level generation.
    source_type = Literal[tuple(source_ids)] if source_ids else str
    statement = pydantic.create_model(
        "Statement",
        text=(str, pydantic.Field(description="One factual claim, one or two sentences.")),
        sources=(list[source_type], ...),
    )
    fields = {"statements": (list[statement], ...)}
    if with_summary:
        # After the statements, so the model sums up findings it has
        # already laid out rather than writing the conclusion first.
        summary = pydantic.create_model(
            "Summary",
            text=(str, pydantic.Field(description="The practical answer, one to three sentences.")),
            sources=(list[source_type], ...),
        )
        fields["summary"] = (summary | None, ...)
    return pydantic.create_model("StatementAnswer", **fields, grounding=(GroundingLevel, ...))


def _answer_in_statements(
    system_prompt: str, user_content: str, source_ids: list[str], with_summary: bool = False,
) -> pydantic.BaseModel:
    model, effort = STATEMENT_ANSWER_MODEL
    completion = client.chat.completions.parse(
        model=model,
        **({"reasoning_effort": effort} if effort else {}),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=_statement_schema(source_ids, with_summary),
    )
    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Model refused to generate: {message.refusal}")
    return message.parsed


def answer_general_question(topic: str) -> tuple[pydantic.BaseModel, list[dict]]:
    # General Q&A (chat mode 3): not tied to one dosage category, so
    # it searches the whole corpus. Returns a summary and statements to verify.
    chunks = _retrieve_general_chunks(topic)
    context_block = "\n\n".join(f"[{c['id']}] ({c['source']}) {c['text']}" for c in chunks)
    parsed = _answer_in_statements(
        _QA_SYSTEM_PROMPT, f"Context:\n{context_block}\n\nQuestion: {topic}", [c["id"] for c in chunks],
        with_summary=True,
    )
    return parsed, chunks


PRESCRIPTION_SOURCE = "prescription"


def answer_prescription_discussion(
    question: str, prescription_summary: str, excerpts: list[dict],
) -> pydantic.BaseModel:
    """`excerpts`: [{"id", "text", "field"}] - the prescription's stored,
    already-verified supporting citations. Returns statements to verify; no
    new retrieval, but each statement is still checked against the excerpt
    it cites, since rephrasing a source can misrepresent it."""
    context = "\n\n".join(f"[{e['id']}] (supports the {e['field']} value) {e['text']}" for e in excerpts)
    return _answer_in_statements(
        _DISCUSSION_SYSTEM_PROMPT,
        f"[{PRESCRIPTION_SOURCE}] Current prescription: {prescription_summary}\n\n"
        f"Supporting excerpts:\n{context or '(none on file)'}\n\nQuestion: {question}",
        [PRESCRIPTION_SOURCE] + [e["id"] for e in excerpts],
    )
