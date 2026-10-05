import logging
import re
from concurrent.futures import ThreadPoolExecutor

from ..rag.generate import (
    build_movement_query,
    generate_for_movement,
    Adjustment,
    build_frequency_query,
    build_intensity_query,
    build_progression_query,
    build_reps_query,
    build_rir_query,
    build_volume_query,
    generate_frequency,
    generate_intensity_load,
    generate_progression_scheme,
    generate_reps,
    generate_rir,
    generate_volume_sets,
    generate_weekly_volume,
    max_sets_per_exercise,
)
from ..rag.verification import verify_citation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..citations import get_or_create_citation
from ..ownership import get_owned_exercise_slot, get_owned_prescription
from ..rag.exercise_selection import ExerciseSelectionError, classify_compound, select_additional_exercises
from ..shared_answers import Answer, GeneratedAnswer, get_or_generate, shared_key

router = APIRouter(prefix="/weekly-prescriptions", tags=["generation"])
mesocycle_router = APIRouter(prefix="/mesocycles", tags=["generation"])
exercise_slot_router = APIRouter(prefix="/exercise-slots", tags=["generation"])
logger = logging.getLogger("uvicorn")

_GENERAL_KNOWLEDGE_NOTE = (
    "This is a general estimate based on established training principles, "
    "not a specific study."
)
_UNSUBSTANTIATED_NOTE = "This value could not be substantiated by the current research corpus."
_PROGRESSION_DERIVED_NOTE = (
    "Calculated from week 1's load by the block's linear progression scheme "
    "- the scheme is cited, this specific week's number is not."
)
_USER_OVERRIDE_NOTE = "Set by you - the current research corpus doesn't support this specific value."
_SUPPORTED_STATUSES = models.SUPPORTED_VERIFICATION_STATUSES


class AdjustmentNotHonored(Exception):
    # Raised (before anything is saved) when an increase/decrease request
    # came back unchanged or moved the wrong way - per the product
    # decision, the current value is kept and the user is told why, rather
    # than pushing past what the research supports.
    def __init__(self, current_value):
        super().__init__(f"Kept at {current_value}")
        self.current_value = current_value


_RPE_PATTERN = re.compile(r"RPE\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RIR_PATTERN = re.compile(r"(\d+)(?:\s*-\s*(\d+))?\s*RIR", re.IGNORECASE)
_REPS_PATTERN = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*$")


def _midpoint(match) -> float:
    low = float(match.group(1))
    return (low + float(match.group(2))) / 2 if match.group(2) else low


def _comparable(value) -> tuple[str, float] | None:
    # Puts a value on a number line where possible: sets are plain ints;
    # load only compares within one unit system (%1RM vs %1RM, RPE vs RPE).
    if isinstance(value, int):
        return ("sets", value)
    rir = _RIR_PATTERN.search(value)  # "1-2 RIR" -> 1.5; "0 RIR (to failure)" -> 0
    if rir:
        return ("RIR", _midpoint(rir))
    reps = _REPS_PATTERN.match(value)  # "8-12" -> 10
    if reps:
        return ("reps", _midpoint(reps))
    percent = _LOAD_PERCENT_PATTERN.search(value)
    if percent:
        return ("%1RM", float(percent.group(1)))
    rpe = _RPE_PATTERN.search(value)
    if rpe:
        return ("RPE", float(rpe.group(1)))
    return None


def _direction_honored(adjustment: Adjustment, old, new) -> bool:
    if adjustment.kind == "set_value":
        return True
    if old == new:
        return False  # the generation prompt's own signal for "research doesn't support moving"
    a, b = _comparable(old), _comparable(new)
    if a is None or b is None or a[0] != b[0]:
        return True  # e.g. %1RM -> RPE: changed, but no honest way to call it higher or lower
    return b[1] > a[1] if adjustment.kind == "increase" else b[1] < a[1]


def _sibling_volume_summary(prescription: models.WeeklyPrescription, db: Session) -> str | None:
    # The cross-exercise volume-coherence problem (datamodel.txt, "ExerciseSlot
    # has a muscle_group field"): two exercises sharing a muscle_group in the
    # same week could each independently be told the full research-backed
    # range and collectively overshoot the real weekly total. This doesn't
    # fix that by enforcing a hard split - it just tells the model what's
    # already prescribed elsewhere so it can reason about the shared budget,
    # the same way a human coach making this one call by hand would already
    # know what the rest of the week looks like.
    slot = prescription.exercise_slot
    mesocycle = slot.day_template.mesocycle

    # Siblings train this muscle as their primary (full sets) or as a
    # secondary (half sets - fractional set counting, so a row's lat work
    # counts toward the lat budget without counting as a full lat set).
    sibling_slots = (
        db.query(models.ExerciseSlot)
        .join(models.DayTemplate)
        .filter(
            models.DayTemplate.mesocycle_id == mesocycle.id,
            or_(
                models.ExerciseSlot.muscle_group == slot.muscle_group,
                models.ExerciseSlot.secondary_muscle_groups.any(slot.muscle_group),
            ),
            models.ExerciseSlot.id != slot.id,
        )
        .all()
    )

    lines = []
    for sibling in sibling_slots:
        sibling_wp = next(
            (wp for wp in sibling.weekly_prescriptions if wp.week_number == prescription.week_number),
            None,
        )
        # Skip a sibling with nothing generated yet (sets=0, load="" is the
        # honest placeholder state from day-cloning/manual creation, not a
        # real allocation) - reporting it as "0 sets" would misleadingly
        # suggest the budget is fully free rather than simply unknown yet.
        if sibling_wp is None or (sibling_wp.sets == 0 and not sibling_wp.load):
            continue
        if sibling.muscle_group == slot.muscle_group:
            lines.append(f"- {sibling.exercise_name}: {sibling_wp.sets} sets")
        else:
            lines.append(
                f"- {sibling.exercise_name}: {sibling_wp.sets} sets "
                f"(trains it secondarily, counts as {sibling_wp.sets / 2:g})"
            )

    return "\n".join(lines) if lines else None


# How strongly each verdict supports a value, for combining two verdicts.
_STATUS_STRENGTH = {"primary_support": 2, "contextual_support": 1}

# Shared answers (app/shared_answers.py) are judged twice: one stored answer
# is reused by every program, and the judge occasionally disagrees with
# itself on borderline excerpts (e.g. '8-12 reps' supported in 2 of 3 runs).
SHARED_JUDGE_PASSES = 2


def _weakest(statuses: list[str]) -> str:
    """The least-supportive verdict: an excerpt only counts as support if
    every pass agreed it does."""
    return min(statuses, key=lambda status: _STATUS_STRENGTH.get(status, 0))


def _verify_chunks(query: str, value, chunk_ids: list[str], chunks_by_id: dict[str, dict], passes: int = 1):
    """Judges every cited chunk for this value, in parallel (a value cites
    several chunks and each judge call takes seconds), `passes` times each,
    keeping the weakest verdict per chunk. Returns (verified: [(chunk,
    status)], any_supported). Chunk ids are schema-constrained to this
    call's retrieved set, so they're always present."""
    chunks = [chunks_by_id[chunk_id] for chunk_id in dict.fromkeys(chunk_ids)]
    if not chunks:
        return [], False
    jobs = [chunk for chunk in chunks for _ in range(passes)]
    with ThreadPoolExecutor(max_workers=min(len(jobs), 10)) as pool:
        verdicts = list(pool.map(lambda chunk: verify_citation(query, value, chunk["text"]), jobs))
    statuses = [_weakest(verdicts[i * passes:(i + 1) * passes]) for i in range(len(chunks))]
    verified = list(zip(chunks, statuses))
    return verified, any(status in _SUPPORTED_STATUSES for status in statuses)


def _generated(attempt, field_name: str) -> GeneratedAnswer:
    """Runs one generation attempt plus the usual single bounded retry: a
    retry is worth it when the model claimed grounding but nothing verified
    (bad luck, not a structural gap); a general_knowledge self-report isn't
    retried (citation_verification.txt section 7)."""
    result, verified, any_supported = attempt()
    if not any_supported and result.grounding != "general_knowledge":
        result, verified, any_supported = attempt()
    return GeneratedAnswer(getattr(result, field_name), result.grounding, any_supported, verified)


def _note_for(answer: Answer, what: str, muscle_group: str, goal: str) -> str | None:
    if answer.supported:
        return None
    if answer.grounding == "general_knowledge":
        return _GENERAL_KNOWLEDGE_NOTE
    logger.warning(
        "Citation verification could not substantiate a generated %s even after retry - "
        "possible corpus gap: muscle_group=%s goal=%s", what, muscle_group, goal,
    )
    return _UNSUBSTANTIATED_NOTE


def _movement(slot: models.ExerciseSlot, db: Session) -> str:
    # AI-picked exercises are classified when picked; one added by hand is
    # classified the first time it's generated, and the answer kept.
    if slot.is_compound is None:
        try:
            slot.is_compound = classify_compound(slot.exercise_name)
        except ExerciseSelectionError:
            raise HTTPException(
                status_code=503,
                detail=f"Couldn't tell whether {slot.exercise_name} is a compound or isolation exercise - try again.",
            )
        db.flush()
    return "compound" if slot.is_compound else "isolation"


def _exercise_answer(db: Session, field: str, goal: str, preference: str, movement: str) -> Answer:
    """Reps, RIR or load for a movement type and goal, shared by every
    program (app/shared_answers.py). The preference only changes RIR."""
    key = shared_key("exercise", field, goal, preference if field == "rir" else "-", movement)
    query = build_movement_query(field, goal, movement)

    def attempt():
        result, chunks = generate_for_movement(field, goal, movement, preference)
        chunks_by_id = {c["id"]: c for c in chunks}
        return (result, *_verify_chunks(
            query, getattr(result, field), result.chunk_ids, chunks_by_id, passes=SHARED_JUDGE_PASSES,
        ))

    return get_or_generate(db, key, field, lambda: _generated(attempt, field))


def _apply_answer(
    prescription: models.WeeklyPrescription, field: str, answer: Answer, muscle_group: str, goal: str,
) -> None:
    # Replaces this field's value, note and citations; other fields keep theirs.
    setattr(prescription, field, answer.value)
    setattr(prescription, f"{field}_grounding_note", _note_for(answer, field, muscle_group, goal))
    prescription.prescription_citations = [pc for pc in prescription.prescription_citations if pc.field != field] + [
        models.PrescriptionCitation(citation_id=citation_id, field=field, verification_status=status)
        for citation_id, status in answer.citations
    ]


def _attempt_generation(
    generate_fn, query_fn, field_name: str, muscle_group: str, goal: str,
    sibling_context: str | None = None, adjustment: Adjustment | None = None,
):
    result, chunks = generate_fn(muscle_group, goal, sibling_context=sibling_context, adjustment=adjustment)
    query = query_fn(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}
    value = getattr(result, field_name)

    return (result, *_verify_chunks(query, value, result.chunk_ids, chunks_by_id))


def _generate_and_persist(
    prescription: models.WeeklyPrescription,
    db: Session,
    generate_fn,
    query_fn,
    field_name: str,
    adjustment: Adjustment | None = None,
) -> models.WeeklyPrescription:
    muscle_group = prescription.exercise_slot.muscle_group
    goal = prescription.exercise_slot.day_template.mesocycle.program.goal
    # Scoped to volume only - load doesn't have a shared weekly budget the
    # way sets do, see generate_intensity_load's own note on this.
    sibling_context = _sibling_volume_summary(prescription, db) if field_name == "sets" else None

    result, verified, any_supported = _attempt_generation(
        generate_fn, query_fn, field_name, muscle_group, goal, sibling_context, adjustment
    )

    # A single bounded retry (never a loop) is worth attempting when the
    # model claimed real grounding but nothing verified it - consistent
    # with stochastic bad luck, not necessarily a structural gap. A
    # self-reported general_knowledge estimate is NOT retried: the model
    # was already honest that nothing supports it, so re-asking the same
    # question against the same corpus has no structural reason to change
    # that (citation_verification.txt section 7).
    if not any_supported and result.grounding != "general_knowledge":
        result, verified, any_supported = _attempt_generation(
            generate_fn, query_fn, field_name, muscle_group, goal, sibling_context, adjustment
        )

    current_value = getattr(prescription, field_name)
    if adjustment and not _direction_honored(adjustment, current_value, getattr(result, field_name)):
        raise AdjustmentNotHonored(current_value)

    setattr(prescription, field_name, getattr(result, field_name))

    # field_name is "sets" or "load" - each has its own note and citations,
    # so regenerating one never touches the other's.
    note_attr = f"{field_name}_grounding_note"
    if any_supported:
        setattr(prescription, note_attr, None)
    elif adjustment and adjustment.kind == "set_value":
        # Distinct from "the model estimated this": the user chose it,
        # and it's applied anyway (an informed override, not a refusal).
        setattr(prescription, note_attr, _USER_OVERRIDE_NOTE)
    elif result.grounding == "general_knowledge":
        setattr(prescription, note_attr, _GENERAL_KNOWLEDGE_NOTE)
    else:
        setattr(prescription, note_attr, _UNSUBSTANTIATED_NOTE)
        logger.warning(
            "Citation verification could not substantiate a generated %s "
            "even after retry - possible corpus gap: muscle_group=%s goal=%s",
            field_name, muscle_group, goal,
        )

    # Replace, don't accumulate: this call's citations fully supersede any
    # left over from a previous generation of THIS field (otherwise
    # re-generating would pile up stale rows). Scoped to the field - the
    # other field's citations still back its own, unchanged value.
    db.query(models.PrescriptionCitation).filter(
        models.PrescriptionCitation.prescription_id == prescription.id,
        models.PrescriptionCitation.field == field_name,
    ).delete()

    for chunk, status in verified:
        citation = get_or_create_citation(db, chunk)
        db.add(models.PrescriptionCitation(
            prescription_id=prescription.id,
            citation_id=citation.id,
            field=field_name,
            verification_status=status,
        ))

    db.commit()
    db.refresh(prescription)
    return prescription


@router.post("/{prescription_id}/generate-volume", response_model=schemas.WeeklyPrescriptionOut)
def generate_volume(
    prescription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    prescription = get_owned_prescription(prescription_id, db, current_user)
    return _generate_and_persist(prescription, db, generate_volume_sets, build_volume_query, "sets")


@router.post("/{prescription_id}/generate-intensity", response_model=schemas.WeeklyPrescriptionOut)
def generate_intensity(
    prescription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    prescription = get_owned_prescription(prescription_id, db, current_user)
    return _generate_and_persist(prescription, db, generate_intensity_load, build_intensity_query, "load")


def field_pipeline(field: str, exercise_name: str, preference: str = "moderate"):
    """(generate_fn, query_fn) for one prescription field.
    Reps and RIR are asked per EXERCISE (a squat and a lateral raise get
    different answers), so the exercise name is bound in here."""
    if field == "sets":
        return generate_volume_sets, build_volume_query
    if field == "load":
        return generate_intensity_load, build_intensity_query
    if field == "reps":
        return (
            lambda m, g, sibling_context=None, adjustment=None: generate_reps(m, g, exercise_name, adjustment=adjustment),
            lambda m, g: build_reps_query(m, g, exercise_name),
        )
    if field == "rir":
        return (
            lambda m, g, sibling_context=None, adjustment=None: generate_rir(
                m, g, exercise_name, adjustment=adjustment, preference=preference,
            ),
            lambda m, g: build_rir_query(m, g, exercise_name),
        )
    raise ValueError(f"Unknown field {field}")


def copy_fields_to_other_weeks(
    base: models.WeeklyPrescription, others: list[models.WeeklyPrescription], fields: tuple[str, ...],
) -> None:
    """Copies the given fields' values, notes and citations from one week to
    the exercise's other weeks. Same claims, so the same citations - copied
    with their verdicts (including retained contradicted/unresolved rows,
    for QA parity); fields not listed keep their own citations."""
    for wp in others:
        for field in fields:
            setattr(wp, field, getattr(base, field))
            setattr(wp, f"{field}_grounding_note", getattr(base, f"{field}_grounding_note"))
        wp.prescription_citations = [pc for pc in wp.prescription_citations if pc.field not in fields] + [
            models.PrescriptionCitation(
                citation_id=pc.citation_id, field=pc.field, verification_status=pc.verification_status,
            )
            for pc in base.prescription_citations
            if pc.field in fields
        ]


def exercise_fields(goal: str) -> tuple[str, ...]:
    # Hypertrophy prescribes effort (RIR) with no load; strength prescribes
    # both a %1RM load and an RIR.
    return ("reps", "load", "rir") if goal == "strength" else ("reps", "rir")


@exercise_slot_router.post("/{exercise_slot_id}/generate", response_model=schemas.ExerciseSlotOut)
def generate_exercise(
    exercise_slot_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Reps, RIR and (strength only) load for this exercise's movement type
    # (compound or isolation), applied to every week of the block. The
    # research isn't exercise- or week-specific, so each answer is shared
    # by every exercise of that type in every program with the same goal
    # (app/shared_answers.py) - asking per exercise cost ~75% of a
    # program's model calls for mostly identical answers. Sets aren't
    # generated here: they come from the muscle's cited weekly volume
    # (generate-weekly-volume). Week-to-week change comes from progression.
    slot = get_owned_exercise_slot(exercise_slot_id, db, current_user)
    weeks = sorted(slot.weekly_prescriptions, key=lambda wp: wp.week_number)
    if not weeks:
        raise HTTPException(status_code=400, detail="This exercise has no weeks to generate.")
    base, rest = weeks[0], weeks[1:]

    program = slot.day_template.mesocycle.program
    fields = exercise_fields(program.goal)
    movement = _movement(slot, db)
    # Every answer first, then apply: storing a new shared answer commits,
    # and nothing half-applied should be pending when it does.
    answers = {
        field: _exercise_answer(db, field, program.goal, program.volume_preference, movement) for field in fields
    }
    for field, answer in answers.items():
        _apply_answer(base, field, answer, slot.muscle_group, program.goal)

    copy_fields_to_other_weeks(base, rest, fields)

    db.commit()
    db.refresh(slot)
    return slot


def _attempt_frequency_generation(muscle_group: str | None, goal: str):
    result, chunks = generate_frequency(muscle_group, goal)
    query = build_frequency_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}

    return (result, *_verify_chunks(
        query, result.frequency, result.chunk_ids, chunks_by_id, passes=SHARED_JUDGE_PASSES,
    ))


def _delete_existing(db: Session, model, mesocycle_id: int, muscle_group: str) -> None:
    # ORM-level delete (not a bulk query delete) so the citation junction
    # rows go with it via the relationship cascade.
    for record in db.query(model).filter(model.mesocycle_id == mesocycle_id, model.muscle_group == muscle_group):
        db.delete(record)
    db.flush()


def _set_derived_load(wp: models.WeeklyPrescription, load: str) -> None:
    # A mechanically-computed load is a different claim than whatever was
    # generated for this week before: any load citations still attached
    # would now vouch for a number they never backed, so they're removed
    # and the note says where the number actually came from.
    wp.load = load
    wp.load_grounding_note = _PROGRESSION_DERIVED_NOTE
    wp.prescription_citations = [pc for pc in wp.prescription_citations if pc.field != "load"]


def _clone_day_for_muscle_group(db: Session, mesocycle: models.Mesocycle, muscle_group: str) -> models.DayTemplate:
    source_day = None
    for day in sorted(mesocycle.day_templates, key=lambda d: d.order):
        if any(slot.muscle_group == muscle_group for slot in day.exercise_slots):
            source_day = day
            break
    if source_day is None:
        raise HTTPException(
            status_code=400,
            detail=f"No existing day trains {muscle_group} in this mesocycle - nothing to clone from.",
        )

    max_order = max((d.order for d in mesocycle.day_templates), default=0)
    new_day = models.DayTemplate(
        mesocycle_id=mesocycle.id,
        name=source_day.name,
        order=max_order + 1,
        rest_days_before=None,  # not yet determined for a newly-added day - a
        # separate, harder problem (optimal rest spacing against every OTHER
        # day) than reconciling the day count itself
    )
    db.add(new_day)
    db.flush()

    for slot in sorted(source_day.exercise_slots, key=lambda s: s.order):
        new_slot = models.ExerciseSlot(
            day_template_id=new_day.id,
            exercise_name=slot.exercise_name,
            muscle_group=slot.muscle_group,
            is_compound=slot.is_compound,
            order=slot.order,
        )
        db.add(new_slot)
        db.flush()
        # Structure (exercises) is cloned; VALUES are deliberately left as
        # honest placeholders, not copied from the source day - copying
        # sets/reps/load directly would silently double-count weekly volume
        # for this muscle group (the cross-exercise coherence problem
        # already flagged as deferred in datamodel.txt) and would present
        # unverified numbers as if they were cited prescriptions. The new
        # day's real values come from the same generate-volume/generate-
        # intensity endpoints every other prescription goes through.
        for week in range(mesocycle.start_week, mesocycle.end_week + 1):
            db.add(models.WeeklyPrescription(
                exercise_slot_id=new_slot.id,
                week_number=week,
                sets=0,
                reps="",
                load="",
            ))

    mesocycle.day_templates.append(new_day)  # keep in-memory list current for the next loop iteration's order/source lookup
    return new_day


@mesocycle_router.post("/{mesocycle_id}/generate-frequency", response_model=schemas.GenerateFrequencyResponse)
def generate_frequency_endpoint(
    mesocycle_id: int,
    request: schemas.GenerateFrequencyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    mesocycle = (
        db.query(models.Mesocycle)
        .options(
            joinedload(models.Mesocycle.program),
            joinedload(models.Mesocycle.day_templates).joinedload(models.DayTemplate.exercise_slots),
        )
        .filter(models.Mesocycle.id == mesocycle_id)
        .first()
    )
    if mesocycle is None or mesocycle.program.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mesocycle not found")

    muscle_group = request.muscle_group
    goal = mesocycle.program.goal

    # One answer per goal, shared by every muscle and program
    # (app/shared_answers.py): the frequency research pools muscles.
    answer = get_or_generate(
        db, shared_key("frequency", goal), "frequency",
        lambda: _generated(lambda: _attempt_frequency_generation(None, goal), "frequency"),
    )
    frequency = int(answer.value)

    # Replace, don't accumulate - same rule as prescription citations. One
    # frequency per mesocycle+muscle_group; its citations cascade with it.
    _delete_existing(db, models.MuscleGroupFrequency, mesocycle.id, muscle_group)

    frequency_record = models.MuscleGroupFrequency(
        mesocycle_id=mesocycle.id,
        muscle_group=muscle_group,
        frequency=frequency,
        grounding_note=_note_for(answer, "frequency", muscle_group, goal),
    )
    db.add(frequency_record)
    db.flush()  # populate frequency_record.id before it's used as a FK below

    for citation_id, status in answer.citations:
        db.add(models.FrequencyCitation(
            frequency_id=frequency_record.id, citation_id=citation_id, verification_status=status,
        ))

    # Reconciliation: only ever ADDS days, never modifies or removes
    # existing structure. Safe specifically because this assumes an
    # initial-setup context (a mesocycle whose days don't yet have real,
    # cited week-by-week history) - not a patch applied to an already-
    # active program, which would hit the still-unsolved exercise-swapping/
    # mid-mesocycle-editing problem in datamodel.txt.
    current_frequency = len({
        day.id for day in mesocycle.day_templates
        if any(slot.muscle_group == muscle_group for slot in day.exercise_slots)
    })
    days_added = []
    shortfall = max(0, frequency - current_frequency) if request.add_days else 0
    for _ in range(shortfall):
        days_added.append(_clone_day_for_muscle_group(db, mesocycle, muscle_group))

    db.commit()
    db.refresh(frequency_record)
    for day in days_added:
        db.refresh(day)

    return schemas.GenerateFrequencyResponse(
        frequency=schemas.MuscleGroupFrequencyOut.model_validate(frequency_record),
        days_added=[schemas.DayTemplateOut.model_validate(d) for d in days_added],
    )


def _attempt_progression_generation(muscle_group: str | None, goal: str):
    result, chunks = generate_progression_scheme(muscle_group, goal)
    query = build_progression_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}

    return (result, *_verify_chunks(
        query, result.scheme, result.chunk_ids, chunks_by_id, passes=SHARED_JUDGE_PASSES,
    ))


_LOAD_PERCENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_LINEAR_WEEKLY_INCREMENT_PERCENT = 2.5  # a standard, uncontroversial convention -
# not itself a research claim needing its own citation, same reasoning already
# used for the (never-built) hypertrophy double-progression increment
_DELOAD_FRACTION_OF_PEAK = 0.6  # standard deload convention: a significant,
# clearly-below-peak reduction in the block's final week


def _apply_linear_progression(mesocycle: models.Mesocycle, muscle_group: str) -> list[models.WeeklyPrescription]:
    updated = []
    total_weeks = mesocycle.end_week - mesocycle.start_week + 1
    has_deload = total_weeks >= 3  # too short a block for progression AND a
    # separate deload week to both make sense

    for day in mesocycle.day_templates:
        for slot in day.exercise_slots:
            if slot.muscle_group != muscle_group:
                continue

            prescriptions_by_week = {wp.week_number: wp for wp in slot.weekly_prescriptions}
            baseline_wp = prescriptions_by_week.get(mesocycle.start_week)
            if baseline_wp is None:
                continue
            match = _LOAD_PERCENT_PATTERN.match(baseline_wp.load.strip())
            if not match:
                continue  # RPE-based, placeholder, or unparseable - nothing to progress from

            baseline_percent = float(match.group(1))
            last_progressive_week = mesocycle.end_week - 1 if has_deload else mesocycle.end_week
            peak_percent = baseline_percent

            for week in range(mesocycle.start_week + 1, last_progressive_week + 1):
                wp = prescriptions_by_week.get(week)
                if wp is None:
                    continue
                offset = week - mesocycle.start_week
                percent = baseline_percent + offset * _LINEAR_WEEKLY_INCREMENT_PERCENT
                peak_percent = max(peak_percent, percent)
                _set_derived_load(wp, f"{percent:g}% 1RM")
                updated.append(wp)

            if has_deload:
                deload_wp = prescriptions_by_week.get(mesocycle.end_week)
                if deload_wp is not None:
                    deload_percent = peak_percent * _DELOAD_FRACTION_OF_PEAK
                    _set_derived_load(deload_wp, f"{deload_percent:g}% 1RM")
                    updated.append(deload_wp)

    return updated


@mesocycle_router.post("/{mesocycle_id}/generate-progression", response_model=schemas.GenerateProgressionResponse)
def generate_progression_endpoint(
    mesocycle_id: int,
    request: schemas.GenerateProgressionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    mesocycle = (
        db.query(models.Mesocycle)
        .options(
            joinedload(models.Mesocycle.program),
            joinedload(models.Mesocycle.day_templates)
            .joinedload(models.DayTemplate.exercise_slots)
            .joinedload(models.ExerciseSlot.weekly_prescriptions),
        )
        .filter(models.Mesocycle.id == mesocycle_id)
        .first()
    )
    if mesocycle is None or mesocycle.program.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mesocycle not found")

    muscle_group = request.muscle_group
    goal = mesocycle.program.goal

    # Progression only applies to strength goals - for hypertrophy, the
    # "implied progression" from staying in a rep range and naturally
    # moving up once you hit the top of it doesn't need a research-grounded
    # scheme, it's just what following a stable rep-range target does on
    # its own. Enforced structurally rather than left as a usage
    # convention, matching how the rest of this app constrains things.
    if goal != "strength":
        raise HTTPException(
            status_code=400,
            detail="Progression generation only applies to strength-goal programs.",
        )

    # One answer per goal, shared by every muscle and program
    # (app/shared_answers.py): periodization research isn't muscle-specific.
    answer = get_or_generate(
        db, shared_key("progression", goal), "scheme",
        lambda: _generated(lambda: _attempt_progression_generation(None, goal), "scheme"),
    )

    _delete_existing(db, models.ProgressionScheme, mesocycle.id, muscle_group)

    scheme_record = models.ProgressionScheme(
        mesocycle_id=mesocycle.id,
        muscle_group=muscle_group,
        scheme=answer.value,
        grounding_note=_note_for(answer, "progression scheme", muscle_group, goal),
    )
    db.add(scheme_record)
    db.flush()  # populate scheme_record.id before it's used as a FK below

    for citation_id, status in answer.citations:
        db.add(models.ProgressionSchemeCitation(
            scheme_id=scheme_record.id, citation_id=citation_id, verification_status=status,
        ))

    # Mechanical application only exists for "linear" - "undulating" needs an
    # alternating pattern, a separate, harder problem not built yet. The
    # scheme itself is still classified and cited either way; only the
    # week-by-week write-back is scoped to linear for now.
    updated_prescriptions = []
    if answer.value == "linear":
        updated_prescriptions = _apply_linear_progression(mesocycle, muscle_group)

    db.commit()
    db.refresh(scheme_record)
    for wp in updated_prescriptions:
        db.refresh(wp)

    return schemas.GenerateProgressionResponse(
        scheme=schemas.ProgressionSchemeOut.model_validate(scheme_record),
        updated_prescriptions=[schemas.WeeklyPrescriptionOut.model_validate(wp) for wp in updated_prescriptions],
    )


_MIN_SETS_PER_EXERCISE = 2  # convention: below this an exercise is barely worth its slot
# Limits on exercises added to fit a muscle's volume under the per-exercise
# cap, so sessions can't balloon; anything still unmet shows as a shortfall.
_MAX_EXERCISES_PER_MUSCLE_PER_DAY = 3
_MAX_EXERCISES_PER_DAY = 10


def _first_week_sets(slot: models.ExerciseSlot) -> int:
    weeks = sorted(slot.weekly_prescriptions, key=lambda wp: wp.week_number)
    return weeks[0].sets if weeks else 0


def _session_targets(mesocycle: models.Mesocycle, muscle_group: str, weekly_sets: int):
    """How a muscle's weekly sets divide across the sessions that train it:
    [(day, main_exercises, secondary_credit, sets_for_main_exercises)].

    Even per SESSION first, then within each session across its exercises,
    so no day carries more of the week than another. Secondary work counts
    at half a set - on the day it happens (a row on Upper 1 gives Upper 1's
    lats half credit); secondary work on days without a main exercise for
    the muscle comes off the weekly total. A remainder set rotates by muscle
    (not always to the first day) so leftovers don't pile onto one day.
    Why even: per-session volume has diminishing returns, so spreading a
    week's sets keeps every session in the productive range - this is the
    cited "even_session_split" rule (see rule_justifications.py)."""
    days = sorted(
        (d for d in mesocycle.day_templates if any(s.muscle_group == muscle_group for s in d.exercise_slots)),
        key=lambda d: d.order,
    )
    if not days:
        return []
    day_ids = {d.id for d in days}

    def credit(slots):
        return 0.5 * sum(_first_week_sets(s) for s in slots if muscle_group in s.secondary_muscle_groups)

    outside = credit(s for d in mesocycle.day_templates if d.id not in day_ids for s in d.exercise_slots)
    per_session_total = max(0, round(weekly_sets - outside))
    base, extra = divmod(per_session_total, len(days))
    start = sum(map(ord, muscle_group)) % len(days)  # rotate which day takes a remainder set
    plan = []
    for i, day in enumerate(days):
        total = base + (1 if (i - start) % len(days) < extra else 0)
        day_credit = credit(day.exercise_slots)
        main = sorted((s for s in day.exercise_slots if s.muscle_group == muscle_group), key=lambda s: s.order)
        plan.append((day, main, day_credit, max(0, round(total - day_credit))))
    return plan


def _add_exercises_to_fit_volume(
    db: Session, mesocycle: models.Mesocycle, muscle_group: str, weekly_sets: int, goal: str,
) -> list[str]:
    """Hypertrophy: where a session's share of the muscle's weekly sets can't
    fit across that session's exercises at the per-exercise cap, add
    exercises for it there (AI-picked to differ from what the day already
    has), so its sets are spread out instead of piled onto one exercise.
    Each session is handled on its own: a full day doesn't push the extra
    work onto another. Returns the names added."""
    cap = max_sets_per_exercise(goal)
    added = []
    for day, main, _credit, target in _session_targets(mesocycle, muscle_group, weekly_sets):
        needed = -(-target // cap) - len(main)  # ceil(target / cap) exercises minus what's there
        room = min(_MAX_EXERCISES_PER_MUSCLE_PER_DAY - len(main), _MAX_EXERCISES_PER_DAY - len(day.exercise_slots))
        count = min(needed, room)
        if count <= 0:
            continue
        try:
            picks = select_additional_exercises(
                day.name, muscle_group, [s.exercise_name for s in day.exercise_slots], count, goal,
            )
        except Exception:
            # Adding exercises is an improvement, not a requirement: without
            # them the volume still splits (capped) and any gap is reported.
            logger.warning("Could not add %s exercises to %s", muscle_group, day.name, exc_info=True)
            continue
        ordered = sorted(day.exercise_slots, key=lambda s: s.order)
        insert_at = max(i for i, s in enumerate(ordered) if s.muscle_group == muscle_group) + 1
        for name, secondaries, is_compound in picks:
            slot = models.ExerciseSlot(
                exercise_name=name, muscle_group=muscle_group, secondary_muscle_groups=secondaries,
                is_compound=is_compound, order=0,
            )
            slot.weekly_prescriptions = [
                models.WeeklyPrescription(week_number=w, sets=0, reps="", load="")
                for w in range(mesocycle.start_week, mesocycle.end_week + 1)
            ]
            ordered.insert(insert_at, slot)
            insert_at += 1
            day.exercise_slots.append(slot)
            added.append(name)
        for i, slot in enumerate(ordered, start=1):  # new exercises sit right after the muscle's existing one
            slot.order = i
    db.flush()
    return added


def _attempt_weekly_volume_generation(muscle_group: str | None, goal: str, preference: str):
    result, chunks = generate_weekly_volume(muscle_group, goal, preference)
    query = build_volume_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}

    return (result, *_verify_chunks(
        query, result.weekly_sets, result.chunk_ids, chunks_by_id, passes=SHARED_JUDGE_PASSES,
    ))


def _split_weekly_sets(mesocycle: models.Mesocycle, muscle_group: str, weekly_sets: int, goal: str) -> int:
    """Splits a muscle's weekly sets evenly across its sessions, then across
    each session's main exercises, writing every week of the block. Returns
    the weekly sets the plan actually delivers (secondary work at half)."""
    all_slots = [slot for day in mesocycle.day_templates for slot in day.exercise_slots]
    total_credit = 0.5 * sum(_first_week_sets(s) for s in all_slots if muscle_group in s.secondary_muscle_groups)
    plan = _session_targets(mesocycle, muscle_group, weekly_sets)
    if not plan:
        return round(total_credit)  # e.g. front delts covered only by pressing

    cap = max_sets_per_exercise(goal)
    sessions = len(plan)
    note = (
        f"Share of {muscle_group}'s {weekly_sets} weekly sets, spread evenly across its {sessions} "
        f"session{'s' if sessions != 1 else ''} and then across each session's exercises (at most {cap} sets "
        f"each). The weekly total is research-cited."
    )
    delivered = total_credit
    for _day, main, _credit, target in plan:
        base, extra = divmod(target, len(main))
        for i, slot in enumerate(main):
            sets = min(cap, max(_MIN_SETS_PER_EXERCISE, base + (1 if i < extra else 0)))
            delivered += sets
            for wp in slot.weekly_prescriptions:
                wp.sets = sets
                wp.sets_grounding_note = note
                # Per-exercise sets citations would vouch for a share the source
                # never stated; the muscle-level record carries the citations.
                wp.prescription_citations = [pc for pc in wp.prescription_citations if pc.field != "sets"]
    return round(delivered)


@mesocycle_router.post("/{mesocycle_id}/generate-weekly-volume", response_model=schemas.GenerateWeeklyVolumeResponse)
def generate_weekly_volume_endpoint(
    mesocycle_id: int,
    request: schemas.GenerateWeeklyVolumeRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    mesocycle = (
        db.query(models.Mesocycle)
        .options(
            joinedload(models.Mesocycle.program),
            joinedload(models.Mesocycle.day_templates)
            .joinedload(models.DayTemplate.exercise_slots)
            .joinedload(models.ExerciseSlot.weekly_prescriptions),
        )
        .filter(models.Mesocycle.id == mesocycle_id)
        .first()
    )
    if mesocycle is None or mesocycle.program.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mesocycle not found")

    muscle_group = request.muscle_group
    goal = mesocycle.program.goal

    preference = mesocycle.program.volume_preference
    # One answer per goal and volume preference, shared by every muscle and
    # program (app/shared_answers.py): the volume meta-analyses pool muscles,
    # and per muscle the answers barely differed (moderate: 12 sets for 12 of
    # 14 muscles) at 14x the cost.
    answer = get_or_generate(
        db, shared_key("weekly_sets", goal, preference), "weekly_sets",
        lambda: _generated(lambda: _attempt_weekly_volume_generation(None, goal, preference), "weekly_sets"),
    )

    _delete_existing(db, models.MuscleGroupVolume, mesocycle.id, muscle_group)
    record = models.MuscleGroupVolume(
        mesocycle_id=mesocycle.id, muscle_group=muscle_group, weekly_sets=int(answer.value),
        grounding_note=_note_for(answer, "weekly volume", muscle_group, goal),
    )
    db.add(record)
    db.flush()
    for citation_id, status in answer.citations:
        db.add(models.VolumeCitation(volume_id=record.id, citation_id=citation_id, verification_status=status))

    added = []
    if goal != "strength":
        added = _add_exercises_to_fit_volume(db, mesocycle, muscle_group, record.weekly_sets, goal)
    delivered = _split_weekly_sets(mesocycle, muscle_group, record.weekly_sets, goal)

    db.commit()
    db.refresh(record)
    return schemas.GenerateWeeklyVolumeResponse(
        volume=schemas.MuscleGroupVolumeOut.model_validate(record),
        delivered_weekly_sets=delivered,
        exercises_added=added,
    )
