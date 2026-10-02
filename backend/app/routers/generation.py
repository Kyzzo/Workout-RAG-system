import logging
import re

from ..rag.generate import (
    Adjustment,
    build_frequency_query,
    build_intensity_query,
    build_progression_query,
    build_volume_query,
    generate_frequency,
    generate_intensity_load,
    generate_progression_scheme,
    generate_volume_sets,
)
from ..rag.verification import verify_citation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..ownership import get_owned_prescription

router = APIRouter(prefix="/weekly-prescriptions", tags=["generation"])
mesocycle_router = APIRouter(prefix="/mesocycles", tags=["generation"])
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


def _comparable(value) -> tuple[str, float] | None:
    # Puts a value on a number line where possible: sets are plain ints;
    # load only compares within one unit system (%1RM vs %1RM, RPE vs RPE).
    if isinstance(value, int):
        return ("sets", value)
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


def _get_or_create_citation(db: Session, chunk: dict) -> models.Citation:
    citation = (
        db.query(models.Citation)
        .filter(models.Citation.qdrant_point_id == chunk["id"])
        .first()
    )
    if citation is None:
        citation = models.Citation(
            title=chunk["source"],
            snippet=chunk["text"],
            qdrant_point_id=chunk["id"],
        )
        db.add(citation)
        db.flush()  # populate citation.id before it's used as a FK below
    return citation


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

    sibling_slots = (
        db.query(models.ExerciseSlot)
        .join(models.DayTemplate)
        .filter(
            models.DayTemplate.mesocycle_id == mesocycle.id,
            models.ExerciseSlot.muscle_group == slot.muscle_group,
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
        lines.append(f"- {sibling.exercise_name}: {sibling_wp.sets} sets")

    return "\n".join(lines) if lines else None


def _attempt_generation(
    generate_fn, query_fn, field_name: str, muscle_group: str, goal: str, use_mechanical_check: bool,
    sibling_context: str | None = None, adjustment: Adjustment | None = None,
):
    result, chunks = generate_fn(muscle_group, goal, sibling_context=sibling_context, adjustment=adjustment)
    query = query_fn(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}
    value = getattr(result, field_name)

    verified = []
    any_supported = False
    for chunk_id in result.chunk_ids:
        chunk = chunks_by_id[chunk_id]  # schema-constrained to this set, always present
        status = verify_citation(query, value, chunk["text"], result.grounding, use_mechanical_check=use_mechanical_check)
        if status in _SUPPORTED_STATUSES:
            any_supported = True
        verified.append((chunk, status))
    return result, verified, any_supported


def _generate_and_persist(
    prescription: models.WeeklyPrescription,
    db: Session,
    generate_fn,
    query_fn,
    field_name: str,
    use_mechanical_check: bool,
    adjustment: Adjustment | None = None,
) -> models.WeeklyPrescription:
    muscle_group = prescription.exercise_slot.muscle_group
    goal = prescription.exercise_slot.day_template.mesocycle.program.goal
    # Scoped to volume only - load doesn't have a shared weekly budget the
    # way sets do, see generate_intensity_load's own note on this.
    sibling_context = _sibling_volume_summary(prescription, db) if field_name == "sets" else None

    result, verified, any_supported = _attempt_generation(
        generate_fn, query_fn, field_name, muscle_group, goal, use_mechanical_check, sibling_context, adjustment
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
            generate_fn, query_fn, field_name, muscle_group, goal, use_mechanical_check, sibling_context, adjustment
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
        citation = _get_or_create_citation(db, chunk)
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
    return _generate_and_persist(
        prescription, db, generate_volume_sets, build_volume_query, "sets", use_mechanical_check=True
    )


@router.post("/{prescription_id}/generate-intensity", response_model=schemas.WeeklyPrescriptionOut)
def generate_intensity(
    prescription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    prescription = get_owned_prescription(prescription_id, db, current_user)
    # use_mechanical_check=False for load: it's a string ("70% 1RM" or an
    # RPE value), and range-containment has no reliable way to compare
    # across those two unit systems - load always escalates to the judge
    # (citation_verification.txt section 3).
    return _generate_and_persist(
        prescription, db, generate_intensity_load, build_intensity_query, "load", use_mechanical_check=False
    )


def _attempt_frequency_generation(muscle_group: str, goal: str):
    result, chunks = generate_frequency(muscle_group, goal)
    query = build_frequency_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}

    verified = []
    any_supported = False
    for chunk_id in result.chunk_ids:
        chunk = chunks_by_id[chunk_id]
        status = verify_citation(query, result.frequency, chunk["text"], result.grounding, use_mechanical_check=True)
        if status in _SUPPORTED_STATUSES:
            any_supported = True
        verified.append((chunk, status))
    return result, verified, any_supported


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

    result, verified, any_supported = _attempt_frequency_generation(muscle_group, goal)
    if not any_supported and result.grounding != "general_knowledge":
        result, verified, any_supported = _attempt_frequency_generation(muscle_group, goal)

    # Replace, don't accumulate - same rule as prescription citations. One
    # frequency per mesocycle+muscle_group; its citations cascade with it.
    _delete_existing(db, models.MuscleGroupFrequency, mesocycle.id, muscle_group)

    frequency_record = models.MuscleGroupFrequency(
        mesocycle_id=mesocycle.id,
        muscle_group=muscle_group,
        frequency=result.frequency,
    )
    if any_supported:
        frequency_record.grounding_note = None
    elif result.grounding == "general_knowledge":
        frequency_record.grounding_note = _GENERAL_KNOWLEDGE_NOTE
    else:
        frequency_record.grounding_note = _UNSUBSTANTIATED_NOTE
        logger.warning(
            "Citation verification could not substantiate a generated frequency "
            "even after retry - possible corpus gap: muscle_group=%s goal=%s",
            muscle_group, goal,
        )
    db.add(frequency_record)
    db.flush()  # populate frequency_record.id before it's used as a FK below

    for chunk, status in verified:
        citation = _get_or_create_citation(db, chunk)
        db.add(models.FrequencyCitation(
            frequency_id=frequency_record.id,
            citation_id=citation.id,
            verification_status=status,
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
    for _ in range(max(0, result.frequency - current_frequency)):
        days_added.append(_clone_day_for_muscle_group(db, mesocycle, muscle_group))

    db.commit()
    db.refresh(frequency_record)
    for day in days_added:
        db.refresh(day)

    return schemas.GenerateFrequencyResponse(
        frequency=schemas.MuscleGroupFrequencyOut.model_validate(frequency_record),
        days_added=[schemas.DayTemplateOut.model_validate(d) for d in days_added],
    )


def _attempt_progression_generation(muscle_group: str, goal: str):
    result, chunks = generate_progression_scheme(muscle_group, goal)
    query = build_progression_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}

    verified = []
    any_supported = False
    for chunk_id in result.chunk_ids:
        chunk = chunks_by_id[chunk_id]
        # use_mechanical_check=False: scheme is a categorical value
        # ("linear"/"undulating"), not a numeric range - point-in-range
        # containment has nothing to check it against, so this always
        # escalates to the judge, same reasoning as load.
        status = verify_citation(query, result.scheme, chunk["text"], result.grounding, use_mechanical_check=False)
        if status in _SUPPORTED_STATUSES:
            any_supported = True
        verified.append((chunk, status))
    return result, verified, any_supported


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

    result, verified, any_supported = _attempt_progression_generation(muscle_group, goal)
    if not any_supported and result.grounding != "general_knowledge":
        result, verified, any_supported = _attempt_progression_generation(muscle_group, goal)

    _delete_existing(db, models.ProgressionScheme, mesocycle.id, muscle_group)

    scheme_record = models.ProgressionScheme(
        mesocycle_id=mesocycle.id,
        muscle_group=muscle_group,
        scheme=result.scheme,
    )
    if any_supported:
        scheme_record.grounding_note = None
    elif result.grounding == "general_knowledge":
        scheme_record.grounding_note = _GENERAL_KNOWLEDGE_NOTE
    else:
        scheme_record.grounding_note = _UNSUBSTANTIATED_NOTE
        logger.warning(
            "Citation verification could not substantiate a generated progression "
            "scheme even after retry - possible corpus gap: muscle_group=%s goal=%s",
            muscle_group, goal,
        )
    db.add(scheme_record)
    db.flush()  # populate scheme_record.id before it's used as a FK below

    for chunk, status in verified:
        citation = _get_or_create_citation(db, chunk)
        db.add(models.ProgressionSchemeCitation(
            scheme_id=scheme_record.id,
            citation_id=citation.id,
            verification_status=status,
        ))

    # Mechanical application only exists for "linear" - "undulating" needs an
    # alternating pattern, a separate, harder problem not built yet. The
    # scheme itself is still classified and cited either way; only the
    # week-by-week write-back is scoped to linear for now.
    updated_prescriptions = []
    if result.scheme == "linear":
        updated_prescriptions = _apply_linear_progression(mesocycle, muscle_group)

    db.commit()
    db.refresh(scheme_record)
    for wp in updated_prescriptions:
        db.refresh(wp)

    return schemas.GenerateProgressionResponse(
        scheme=schemas.ProgressionSchemeOut.model_validate(scheme_record),
        updated_prescriptions=[schemas.WeeklyPrescriptionOut.model_validate(wp) for wp in updated_prescriptions],
    )
