# Volume is cited where the research makes the claim - weekly sets per
# muscle - then split mechanically across that muscle's exercises, capped per
# exercise (4 hypertrophy, 5 strength) so a 2-day split can't put a whole
# week's volume into one exercise.
from types import SimpleNamespace
from typing import get_args
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.generation import _split_weekly_sets, generate_weekly_volume_endpoint


def _block(db_session, goal="hypertrophy", weeks=2):
    user = models.User(clerk_user_id=f"test-clerk-id-volume-{goal}")
    db_session.add(user)
    db_session.flush()
    program = models.Program(user_id=user.id, goal=goal)
    db_session.add(program)
    db_session.flush()
    mesocycle = models.Mesocycle(program_id=program.id, name="Block", start_week=1, end_week=weeks)
    db_session.add(mesocycle)
    db_session.flush()
    day = models.DayTemplate(mesocycle_id=mesocycle.id, name="Day", order=1)
    db_session.add(day)
    db_session.flush()
    return user, mesocycle, day


def _exercise(db_session, day, name, primary, secondaries=(), sets=0, weeks=2):
    slot = models.ExerciseSlot(
        day_template_id=day.id, exercise_name=name, muscle_group=primary,
        secondary_muscle_groups=list(secondaries), order=len(day.exercise_slots) + 1,
    )
    slot.weekly_prescriptions = [
        models.WeeklyPrescription(week_number=w, sets=sets, reps="", load="") for w in range(1, weeks + 1)
    ]
    db_session.add(slot)
    db_session.flush()
    db_session.refresh(day)
    return slot


def _sets(slot):
    return [wp.sets for wp in sorted(slot.weekly_prescriptions, key=lambda wp: wp.week_number)]


# --- the split ------------------------------------------------------------------

def test_one_exercise_never_gets_the_whole_week(db_session):
    # The reported problem: 2-day Upper/Lower, bench is the only chest
    # exercise, research says 12 sets/week -> previously 12 sets of bench.
    _, mesocycle, day = _block(db_session)
    bench = _exercise(db_session, day, "Bench Press", "chest")

    delivered = _split_weekly_sets(mesocycle, "chest", 12, "hypertrophy")

    assert _sets(bench) == [4, 4]  # capped, every week
    assert delivered == 4  # the shortfall is reported, not hidden


def test_strength_cap_is_five(db_session):
    _, mesocycle, day = _block(db_session, goal="strength")
    squat = _exercise(db_session, day, "Back Squat", "quadriceps")

    _split_weekly_sets(mesocycle, "quadriceps", 12, "strength")

    assert _sets(squat) == [5, 5]


def test_split_is_even_and_secondary_work_counts_half(db_session):
    _, mesocycle, day = _block(db_session)
    _exercise(db_session, day, "Barbell Row", "upper back", ["lats"], sets=4)  # 2 sets of lat credit
    pulldown = _exercise(db_session, day, "Lat Pulldown", "lats")
    pullup = _exercise(db_session, day, "Pull-Up", "lats")

    delivered = _split_weekly_sets(mesocycle, "lats", 9, "hypertrophy")

    # 9 - 2 (half of the row's 4) = 7 -> 4 + 3, first exercise gets the extra
    assert (_sets(pulldown), _sets(pullup)) == ([4, 4], [3, 3])
    assert delivered == 9


def test_every_exercise_gets_at_least_two_sets(db_session):
    _, mesocycle, day = _block(db_session)
    flyes = [_exercise(db_session, day, f"Fly {i}", "chest") for i in range(3)]

    _split_weekly_sets(mesocycle, "chest", 3, "hypertrophy")

    assert [_sets(f)[0] for f in flyes] == [2, 2, 2]


def test_split_marks_sets_as_derived_and_drops_per_exercise_citations(db_session):
    _, mesocycle, day = _block(db_session)
    bench = _exercise(db_session, day, "Bench Press", "chest")
    citation = models.Citation(title="old", snippet="s", qdrant_point_id="old-1")
    db_session.add(citation)
    db_session.flush()
    for wp in bench.weekly_prescriptions:
        wp.prescription_citations.append(
            models.PrescriptionCitation(citation_id=citation.id, field="sets", verification_status="primary_support")
        )
        wp.prescription_citations.append(
            models.PrescriptionCitation(citation_id=citation.id, field="load", verification_status="primary_support")
        )
    db_session.flush()

    _split_weekly_sets(mesocycle, "chest", 6, "hypertrophy")

    for wp in bench.weekly_prescriptions:
        assert [pc.field for pc in wp.prescription_citations] == ["load"]  # load's own citations stay
        assert wp.sets_grounding_note.startswith("Share of chest's 6 weekly sets")


def test_muscle_with_no_main_exercise_only_counts_secondary_credit(db_session):
    _, mesocycle, day = _block(db_session)
    _exercise(db_session, day, "Bench Press", "chest", ["front delts"], sets=4)

    assert _split_weekly_sets(mesocycle, "front delts", 8, "hypertrophy") == 2


def test_single_value_generation_is_capped_by_the_schema():
    with patch("app.rag.generate._generate_field") as field:
        from app.rag.generate import generate_volume_sets

        generate_volume_sets("chest", "hypertrophy")
        assert get_args(field.call_args.args[1]) == (1, 2, 3, 4)
        generate_volume_sets("chest", "strength")
        assert get_args(field.call_args.args[1]) == (1, 2, 3, 4, 5)


# --- the endpoint -----------------------------------------------------------------

def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_endpoint_cites_the_weekly_total_and_replaces_previous(mock_generate, _verify, db_session):
    user, mesocycle, day = _block(db_session)
    bench = _exercise(db_session, day, "Bench Press", "chest")
    fly = _exercise(db_session, day, "Cable Fly", "chest")
    mock_generate.return_value = (
        SimpleNamespace(weekly_sets=12, chunk_ids=["v-1"], grounding="fully_grounded"), _chunks("v-1"),
    )
    request = schemas.GenerateWeeklyVolumeRequest(muscle_group="chest")

    generate_weekly_volume_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)
    result = generate_weekly_volume_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.volume.weekly_sets == 12
    assert [c.citation.title for c in result.volume.supporting_citations] == ["paper-v-1"]
    assert result.delivered_weekly_sets == 8  # 2 exercises x 4, short of 12
    assert db_session.query(models.MuscleGroupVolume).filter_by(mesocycle_id=mesocycle.id).count() == 1
    assert (_sets(bench), _sets(fly)) == ([4, 4], [4, 4])


def test_endpoint_ownership_enforced(db_session, other_user):
    _, mesocycle, _ = _block(db_session)

    with pytest.raises(HTTPException) as exc_info:
        generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=other_user,
        )

    assert exc_info.value.status_code == 404
