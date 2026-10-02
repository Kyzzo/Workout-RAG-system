import pydantic
import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.programs import list_programs
from app.routers.structure import (
    create_day_template,
    create_exercise_slot,
    create_mesocycle,
    delete_day_template,
    delete_exercise_slot,
)


def _mesocycle_of(prescription):
    return prescription.exercise_slot.day_template.mesocycle


def test_list_programs_only_returns_own(db_session, owner_and_prescription, other_user):
    user, prescription = owner_and_prescription
    db_session.add(models.Program(user_id=other_user.id, goal="strength"))
    db_session.flush()

    programs = list_programs(db=db_session, current_user=user)

    assert [p.id for p in programs] == [_mesocycle_of(prescription).program_id]


def test_create_mesocycle(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    program_id = _mesocycle_of(prescription).program_id  # existing block covers weeks 1-6

    request = schemas.MesocycleCreate(name="Intensification", start_week=7, end_week=10)
    mesocycle = create_mesocycle(program_id=program_id, request=request, db=db_session, current_user=user)

    assert mesocycle.program_id == program_id
    assert (mesocycle.start_week, mesocycle.end_week) == (7, 10)


def test_create_mesocycle_rejects_overlapping_weeks(db_session, owner_and_prescription):
    # week_number is absolute across the program, so overlapping blocks
    # would give one exercise-week two competing prescriptions.
    user, prescription = owner_and_prescription
    program_id = _mesocycle_of(prescription).program_id

    request = schemas.MesocycleCreate(name="Overlap", start_week=6, end_week=8)
    with pytest.raises(HTTPException) as exc_info:
        create_mesocycle(program_id=program_id, request=request, db=db_session, current_user=user)

    assert exc_info.value.status_code == 400


def test_mesocycle_create_rejects_inverted_week_range():
    with pytest.raises(pydantic.ValidationError):
        schemas.MesocycleCreate(name="Backwards", start_week=5, end_week=2)


def test_create_mesocycle_ownership_enforced(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    program_id = _mesocycle_of(prescription).program_id

    request = schemas.MesocycleCreate(name="Intruder", start_week=7, end_week=8)
    with pytest.raises(HTTPException) as exc_info:
        create_mesocycle(program_id=program_id, request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


def test_create_day_appends_to_rotation(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mesocycle = _mesocycle_of(prescription)  # already has "Push" at order 1

    request = schemas.DayTemplateCreate(name="Pull", rest_days_before=1)
    day = create_day_template(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert day.order == 2
    assert day.rest_days_before == 1
    assert day.exercise_slots == []


def test_create_day_ownership_enforced(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mesocycle = _mesocycle_of(prescription)

    request = schemas.DayTemplateCreate(name="Intruder")
    with pytest.raises(HTTPException) as exc_info:
        create_day_template(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


def test_create_exercise_adds_placeholder_prescription_per_week(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    day = prescription.exercise_slot.day_template  # block covers weeks 1-6, already has one exercise

    request = schemas.ExerciseSlotCreate(exercise_name="Cable Fly", muscle_group="  Chest ")
    slot = create_exercise_slot(day_template_id=day.id, request=request, db=db_session, current_user=user)

    assert slot.order == 2
    # Normalized so it matches the existing "chest" slot for sibling-volume
    # and frequency lookups, which compare muscle_group by exact string.
    assert slot.muscle_group == "chest"
    assert [wp.week_number for wp in slot.weekly_prescriptions] == [1, 2, 3, 4, 5, 6]
    assert all(wp.sets == 0 and wp.reps == "" and wp.load == "" for wp in slot.weekly_prescriptions)


def test_exercise_create_rejects_blank_muscle_group():
    with pytest.raises(pydantic.ValidationError):
        schemas.ExerciseSlotCreate(exercise_name="Mystery Lift", muscle_group="   ")


def test_create_exercise_ownership_enforced(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    day = prescription.exercise_slot.day_template

    request = schemas.ExerciseSlotCreate(exercise_name="Intruder Press", muscle_group="chest")
    with pytest.raises(HTTPException) as exc_info:
        create_exercise_slot(day_template_id=day.id, request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


# --- deletes: cascade through ExerciseSlot -> WeeklyPrescription ->
# PrescriptionCitation, but keep the shared Citation row, which other
# prescriptions may also cite.

def _cite(db_session, prescription):
    citation = models.Citation(title="paper", snippet="excerpt", qdrant_point_id="chunk-1")
    db_session.add(citation)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=prescription.id, citation_id=citation.id, field="sets", verification_status="primary_support",
    ))
    db_session.flush()
    return citation


def test_delete_day_cascades_but_keeps_shared_citation(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    day_id = prescription.exercise_slot.day_template_id
    slot_id = prescription.exercise_slot_id
    citation = _cite(db_session, prescription)

    delete_day_template(day_template_id=day_id, db=db_session, current_user=user)

    db_session.expire_all()
    assert db_session.get(models.DayTemplate, day_id) is None
    assert db_session.get(models.ExerciseSlot, slot_id) is None
    assert db_session.query(models.WeeklyPrescription).filter_by(exercise_slot_id=slot_id).count() == 0
    assert db_session.query(models.PrescriptionCitation).filter_by(prescription_id=prescription.id).count() == 0
    assert db_session.get(models.Citation, citation.id) is not None


def test_delete_day_ownership_enforced(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    day_id = prescription.exercise_slot.day_template_id

    with pytest.raises(HTTPException) as exc_info:
        delete_day_template(day_template_id=day_id, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    assert db_session.get(models.DayTemplate, day_id) is not None


def test_delete_exercise_leaves_rest_of_day(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    day = prescription.exercise_slot.day_template
    request = schemas.ExerciseSlotCreate(exercise_name="Cable Fly", muscle_group="chest")
    kept = create_exercise_slot(day_template_id=day.id, request=request, db=db_session, current_user=user)
    removed_slot_id = prescription.exercise_slot_id
    _cite(db_session, prescription)

    delete_exercise_slot(exercise_slot_id=removed_slot_id, db=db_session, current_user=user)

    db_session.expire_all()
    assert db_session.get(models.ExerciseSlot, removed_slot_id) is None
    assert db_session.query(models.PrescriptionCitation).filter_by(prescription_id=prescription.id).count() == 0
    assert [s.id for s in db_session.get(models.DayTemplate, day.id).exercise_slots] == [kept.id]


def test_delete_exercise_ownership_enforced(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    slot_id = prescription.exercise_slot_id

    with pytest.raises(HTTPException) as exc_info:
        delete_exercise_slot(exercise_slot_id=slot_id, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    assert db_session.get(models.ExerciseSlot, slot_id) is not None
