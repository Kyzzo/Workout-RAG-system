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

    assert _sets(bench) == [3, 3]  # capped at 3 for hypertrophy, every week
    assert delivered == 3  # the shortfall is reported, not hidden


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

    delivered = _split_weekly_sets(mesocycle, "lats", 7, "hypertrophy")

    # 7 - 2 (half of the row's 4) = 5 -> 3 + 2, first exercise gets the extra
    assert (_sets(pulldown), _sets(pullup)) == ([3, 3], [2, 2])
    assert delivered == 7


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
        assert get_args(field.call_args.args[1]) == (1, 2, 3)
        generate_volume_sets("chest", "strength")
        assert get_args(field.call_args.args[1]) == (1, 2, 3, 4, 5)


# --- the endpoint -----------------------------------------------------------------

def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_endpoint_cites_the_weekly_total_and_replaces_previous(mock_generate, _verify, db_session):
    user, mesocycle, day = _block(db_session, goal="strength")  # strength: no exercises added
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
    assert result.delivered_weekly_sets == 10  # 2 exercises x 5 (strength cap), short of 12
    assert result.exercises_added == []
    assert db_session.query(models.MuscleGroupVolume).filter_by(mesocycle_id=mesocycle.id).count() == 1
    assert (_sets(bench), _sets(fly)) == ([5, 5], [5, 5])


def test_endpoint_ownership_enforced(db_session, other_user):
    _, mesocycle, _ = _block(db_session)

    with pytest.raises(HTTPException) as exc_info:
        generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=other_user,
        )

    assert exc_info.value.status_code == 404


# --- volume preference --------------------------------------------------------------

@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_program_volume_preference_reaches_weekly_volume_generation(mock_generate, _verify, db_session):
    user, mesocycle, day = _block(db_session)
    mesocycle.program.volume_preference = "minimal"
    _exercise(db_session, day, "Bench Press", "chest")
    mock_generate.return_value = (SimpleNamespace(weekly_sets=6, chunk_ids=[], grounding="general_knowledge"), [])

    generate_weekly_volume_endpoint(
        mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
        db=db_session, current_user=user,
    )

    assert mock_generate.call_args.args == ("chest", "hypertrophy", "minimal")


@pytest.mark.parametrize("preference, expected", [
    ("minimal", "LOWEST weekly set count"),
    ("high", "HIGH end"),
    # moderate is guided too: unguided, it aimed for the 'no detectable
    # superiority' point (~31 sets) as a target
    ("moderate", "effective AND efficient"),
])
def test_preference_becomes_generation_guidance(preference, expected):
    from app.rag import generate

    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None, parsed="parsed"))])
    with patch.object(generate, "_retrieve_chunks", return_value=_chunks("v-1")), \
            patch.object(generate.client.chat.completions, "parse", return_value=completion) as parse:
        generate.generate_weekly_volume("chest", "hypertrophy", preference)

    prompt = parse.call_args.kwargs["messages"][-1]["content"]
    assert "User preference:" in prompt and expected in prompt



# --- spreading a muscle's sets across more exercises (hypertrophy) -------------

def _added(names_by_call):
    """Fake select_additional_exercises: returns the next queued names."""
    calls = []

    def fake(day_name, muscle_group, existing, count, goal):
        calls.append((day_name, muscle_group, count))
        return [(f"{muscle_group} variation {len(calls)}.{i}", [], False) for i in range(count)]
    return fake, calls


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_hypertrophy_adds_exercises_instead_of_piling_sets_on_one(mock_generate, _verify, db_session):
    # 4 chest sets for one session: 2 bench + 2 of a second chest exercise,
    # not 4 sets of bench.
    user, mesocycle, day = _block(db_session)
    _exercise(db_session, day, "Bench Press", "chest", sets=0)
    _exercise(db_session, day, "Lateral Raise", "side delts", sets=0)
    mock_generate.return_value = (SimpleNamespace(weekly_sets=4, chunk_ids=[], grounding="general_knowledge"), [])
    fake, calls = _added(None)

    with patch("app.routers.generation.select_additional_exercises", side_effect=fake):
        result = generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=user,
        )

    assert calls == [("Day", "chest", 1)]
    assert result.exercises_added == ["chest variation 1.0"]
    db_session.expire_all()
    slots = sorted(db_session.get(models.DayTemplate, day.id).exercise_slots, key=lambda s: s.order)
    # the new chest exercise sits right after the existing one, before delts
    assert [s.exercise_name for s in slots] == ["Bench Press", "chest variation 1.0", "Lateral Raise"]
    assert [_sets(s)[0] for s in slots[:2]] == [2, 2]
    assert len(slots[1].weekly_prescriptions) == 2  # placeholder rows for every week of the block


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_no_exercises_added_when_volume_already_fits(mock_generate, _verify, db_session):
    # e.g. the minimal preference: a low weekly target fits one exercise
    user, mesocycle, day = _block(db_session)
    _exercise(db_session, day, "Bench Press", "chest")
    mock_generate.return_value = (SimpleNamespace(weekly_sets=3, chunk_ids=[], grounding="general_knowledge"), [])

    with patch("app.routers.generation.select_additional_exercises") as add:
        result = generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=user,
        )

    add.assert_not_called()
    assert result.exercises_added == []


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_added_exercises_stop_at_three_per_muscle_per_day(mock_generate, _verify, db_session):
    user, mesocycle, day = _block(db_session)
    _exercise(db_session, day, "Bench Press", "chest")
    mock_generate.return_value = (SimpleNamespace(weekly_sets=20, chunk_ids=[], grounding="general_knowledge"), [])
    fake, calls = _added(None)

    with patch("app.routers.generation.select_additional_exercises", side_effect=fake):
        result = generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=user,
        )

    assert len(result.exercises_added) == 2  # 1 existing + 2 added = 3 chest exercises max
    assert result.delivered_weekly_sets == 9  # 3 x 3, the rest shows as a shortfall


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_failed_exercise_picking_still_splits_volume(mock_generate, _verify, db_session):
    user, mesocycle, day = _block(db_session)
    bench = _exercise(db_session, day, "Bench Press", "chest")
    mock_generate.return_value = (SimpleNamespace(weekly_sets=6, chunk_ids=[], grounding="general_knowledge"), [])

    with patch("app.routers.generation.select_additional_exercises", side_effect=RuntimeError("model down")):
        result = generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=user,
        )

    assert result.exercises_added == []
    assert _sets(bench) == [3, 3]


# --- even across sessions (no front-loading) -----------------------------------

def _second_day(db_session, mesocycle, name="Day 2"):
    day = models.DayTemplate(mesocycle_id=mesocycle.id, name=name, order=len(mesocycle.day_templates) + 1)
    db_session.add(day)
    db_session.flush()
    db_session.refresh(mesocycle)
    return day


def test_weekly_sets_split_evenly_per_session(db_session):
    _, mesocycle, day1 = _block(db_session)
    day2 = _second_day(db_session, mesocycle)
    a = _exercise(db_session, day1, "Bench Press", "chest")
    b = _exercise(db_session, day1, "Incline Press", "chest")
    c = _exercise(db_session, day2, "Dumbbell Press", "chest")
    d = _exercise(db_session, day2, "Cable Fly", "chest")
    db_session.refresh(mesocycle)

    _split_weekly_sets(mesocycle, "chest", 10, "hypertrophy")

    # 5 per session, not 3+3 on day 1 and 2+2 on day 2
    assert [_sets(x)[0] for x in (a, b)] == [3, 2] and [_sets(x)[0] for x in (c, d)] == [3, 2]


def test_remainder_set_rotates_by_muscle_not_always_day_one(db_session):
    from app.routers.generation import _session_targets

    _, mesocycle, day1 = _block(db_session)
    day2 = _second_day(db_session, mesocycle)
    for day in (day1, day2):
        _exercise(db_session, day, f"{day.name} press", "chest")
        _exercise(db_session, day, f"{day.name} pulldown", "lats")
    db_session.refresh(mesocycle)

    chest = [t for *_, t in _session_targets(mesocycle, "chest", 5)]
    lats = [t for *_, t in _session_targets(mesocycle, "lats", 5)]

    assert sorted(chest) == [2, 3] and sorted(lats) == [2, 3]
    assert chest != lats  # different muscles put their extra set on different days


def test_secondary_credit_counts_on_its_own_day(db_session):
    _, mesocycle, day1 = _block(db_session)
    day2 = _second_day(db_session, mesocycle)
    _exercise(db_session, day1, "Barbell Row", "upper back", ["lats"], sets=4)  # 2 lat sets of credit, day 1 only
    p1 = _exercise(db_session, day1, "Pulldown", "lats")
    p2 = _exercise(db_session, day2, "Pull-Up", "lats")
    db_session.refresh(mesocycle)

    _split_weekly_sets(mesocycle, "lats", 6, "hypertrophy")

    # 3 per session: day 1 already has 2 from the row, so its pulldown gets the 2-set floor
    assert (_sets(p1)[0], _sets(p2)[0]) == (2, 3)


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_weekly_volume")
def test_a_full_day_doesnt_push_its_share_onto_another(mock_generate, _verify, db_session):
    user, mesocycle, day1 = _block(db_session)
    day2 = _second_day(db_session, mesocycle)
    _exercise(db_session, day1, "Bench Press", "chest")
    for i in range(9):  # day 1 is at the 10-exercise limit
        _exercise(db_session, day1, f"Filler {i}", "abs")
    _exercise(db_session, day2, "Dumbbell Press", "chest")
    db_session.refresh(mesocycle)
    mock_generate.return_value = (SimpleNamespace(weekly_sets=12, chunk_ids=[], grounding="general_knowledge"), [])
    fake, calls = _added(None)

    with patch("app.routers.generation.select_additional_exercises", side_effect=fake):
        generate_weekly_volume_endpoint(
            mesocycle_id=mesocycle.id, request=schemas.GenerateWeeklyVolumeRequest(muscle_group="chest"),
            db=db_session, current_user=user,
        )

    # 6 per session: day 2 gets its second chest exercise; day 1 stays capped
    # at 3 (shortfall) rather than day 2 taking on day 1's sets
    assert calls == [("Day 2", "chest", 1)]
    db_session.expire_all()
    day2_sets = [_sets(s)[0] for s in db_session.get(models.DayTemplate, day2.id).exercise_slots if s.muscle_group == "chest"]
    assert day2_sets == [3, 3]
