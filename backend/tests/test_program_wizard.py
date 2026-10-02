# Program wizard: split -> planned days -> AI-picked exercises -> a full
# structure with placeholder weeks, ready for per-exercise generation.
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pydantic
import pytest
from fastapi import HTTPException

from app import models, schemas
from app.rag.exercise_selection import ExerciseSelectionError, _problems, select_exercises
from app.routers.generation import generate_frequency_endpoint
from app.routers.programs import generate_program
from app.splits import SPLITS, plan_days


@pytest.fixture()
def user(db_session):
    user = models.User(clerk_user_id="test-clerk-id-wizard")
    db_session.add(user)
    db_session.flush()
    return user


def _picks_covering(days):
    # A valid selection: one exercise per target muscle group (min 4 per day).
    result = []
    for day in days:
        picks = [(f"{day.name} {group} lift", group, []) for group in day.muscle_groups]
        while len(picks) < 4:
            picks.append((f"{day.name} extra {len(picks)}", day.muscle_groups[0], []))
        result.append(picks)
    return result


# --- splits ------------------------------------------------------------------

def test_plan_days_numbers_repeats_and_spaces_rest():
    days = plan_days(SPLITS["ppl"], 6)
    assert [d.name for d in days] == ["Push 1", "Pull 1", "Legs 1", "Push 2", "Pull 2", "Legs 2"]

    three = plan_days(SPLITS["full_body"], 3)
    assert [d.name for d in three] == ["Full Body 1", "Full Body 2", "Full Body 3"]
    assert [d.rest_days_before for d in three] == [None, 1, 1]  # Mon/Wed/Fri

    two = plan_days(SPLITS["upper_lower"], 2)
    assert [(d.name, d.rest_days_before) for d in two] == [("Upper", None), ("Lower", 2)]


def test_every_allowed_day_count_fits_the_week():
    for split in SPLITS.values():
        for n in split.allowed_days:
            days = plan_days(split, n)
            rest = sum(d.rest_days_before or 0 for d in days)
            assert len(days) == n and rest <= 7 - n


@pytest.mark.parametrize("split, days", [("ppl", 4), ("upper_lower", 3), ("arnold", 5), ("nonsense", 3)])
def test_request_rejects_day_counts_that_dont_fit(split, days):
    with pytest.raises(pydantic.ValidationError):
        schemas.ProgramGenerateRequest(goal="hypertrophy", split=split, days_per_week=days)


# --- exercise selection --------------------------------------------------------

def _completion(parsed):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None, parsed=parsed))])


def _parsed(days, picks_per_day):
    # Builds the structured response shape: the first pick for each target
    # muscle goes in that muscle's field (None if there isn't one), the rest
    # go in extras.
    def exercise(name, sec):
        return SimpleNamespace(exercise_name=name, is_compound=False, secondary_muscle_groups=sec)

    day_responses = {}
    for i, (day, picks) in enumerate(zip(days, picks_per_day)):
        remaining = list(picks)
        fields = {}
        for group in day.muscle_groups:
            match = next((p for p in remaining if p[1] == group), None)
            if match:
                remaining.remove(match)
            fields[group.replace(" ", "_")] = exercise(match[0], match[2]) if match else None
        fields["extras"] = [
            SimpleNamespace(exercise_name=n, is_compound=False, muscle_group=g, secondary_muscle_groups=sec)
            for n, g, sec in remaining
        ]
        day_responses[f"day_{i + 1}"] = SimpleNamespace(**fields)
    return SimpleNamespace(**day_responses)


def test_selection_retries_once_when_a_muscle_group_is_missed():
    days = plan_days(SPLITS["ppl"], 3)
    good = _picks_covering(days)
    bad = [list(good[0]), good[1], good[2]]
    bad[0] = [p for p in bad[0] if p[1] != "triceps"] + [("Extra Press", "chest", [])]  # Push skips triceps
    parse = MagicMock(side_effect=[_completion(_parsed(days, bad)), _completion(_parsed(days, good))])

    with patch("app.rag.exercise_selection.client.chat.completions.parse", parse):
        result = select_exercises(days, "hypertrophy", "Push/Pull/Legs")

    assert result == good
    retry_prompt = parse.call_args_list[1].kwargs["messages"][-1]["content"]
    assert "Push has no exercise for triceps" in retry_prompt


def test_selection_gives_up_after_one_retry():
    days = plan_days(SPLITS["ppl"], 3)
    bad = _picks_covering(days)
    bad[1] = [("Row", "upper back", ["lats", "rear delts"])] * 4  # Pull never covers biceps
    parse = MagicMock(return_value=_completion(_parsed(days, bad)))

    with patch("app.rag.exercise_selection.client.chat.completions.parse", parse):
        with pytest.raises(ExerciseSelectionError):
            select_exercises(days, "hypertrophy", "Push/Pull/Legs")

    assert parse.call_count == 2


# --- generate_program --------------------------------------------------------------

@patch("app.routers.programs.select_exercises")
def test_generate_program_builds_the_full_structure(mock_select, db_session, user):
    mock_select.side_effect = lambda days, goal, label: _picks_covering(days)
    request = schemas.ProgramGenerateRequest(goal="strength", split="upper_lower", days_per_week=4, weeks=5)

    program = schemas.ProgramOut.model_validate(generate_program(request=request, db=db_session, current_user=user))

    assert program.user_id == user.id and program.goal == "strength"
    [block] = program.mesocycles
    assert (block.name, block.start_week, block.end_week) == ("Upper/Lower, 4 days/week", 1, 5)
    assert [(d.name, d.order, d.rest_days_before) for d in block.day_templates] == [
        ("Upper 1", 1, None), ("Lower 1", 2, 1), ("Upper 2", 3, 1), ("Lower 2", 4, 0),
    ]
    upper = block.day_templates[0]
    assert {s.muscle_group for s in upper.exercise_slots} == set(SPLITS["upper_lower"].day_types[0].muscle_groups)
    for slot in upper.exercise_slots:
        assert [(wp.week_number, wp.sets, wp.load) for wp in slot.weekly_prescriptions] == [
            (w, 0, "") for w in range(1, 6)  # placeholders, ready for generation
        ]


@patch("app.routers.programs.select_exercises", side_effect=ExerciseSelectionError("no"))
def test_failed_selection_leaves_no_half_built_program(_select, db_session, user):
    request = schemas.ProgramGenerateRequest(goal="hypertrophy", split="ppl", days_per_week=3)

    with pytest.raises(HTTPException) as exc_info:
        generate_program(request=request, db=db_session, current_user=user)

    assert exc_info.value.status_code == 502
    assert db_session.query(models.Program).filter_by(user_id=user.id).count() == 0


# --- frequency as comparison only ------------------------------------------------

@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_frequency")
def test_frequency_compare_only_never_adds_days(mock_generate, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription  # one chest day
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    mock_generate.return_value = (
        SimpleNamespace(frequency=3, chunk_ids=["f-1"], grounding="fully_grounded"),
        [{"id": "f-1", "text": "t", "source": "paper"}],
    )

    request = schemas.GenerateFrequencyRequest(muscle_group="chest", add_days=False)
    result = generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.frequency.frequency == 3  # still generated and cited
    assert result.days_added == []
    db_session.refresh(mesocycle)
    assert len(mesocycle.day_templates) == 1


# --- finer muscle groups + secondary muscles ----------------------------------

def test_front_delts_and_lower_back_may_be_covered_as_secondaries_but_lats_may_not():
    days = plan_days(SPLITS["ppl"], 3)  # Push lists front delts; Legs lists lower back
    picks = _picks_covering(days)
    picks[0] = [p for p in picks[0] if p[1] != "front delts"] + [("Cable Fly", "chest", [])]
    picks[0][0] = ("Barbell Bench Press", "chest", ["front delts", "triceps"])
    picks[2] = [p for p in picks[2] if p[1] != "lower back"]
    picks[2][1] = ("Romanian Deadlift", "hamstrings", ["glutes", "lower back"])
    assert _problems(days, _parsed(days, picks)) == []

    # lats are NOT secondary-coverable: a Pull day whose only lat work is a
    # row's secondary is missing its vertical pull.
    no_lats = [list(day) for day in picks]
    no_lats[1] = [p for p in no_lats[1] if p[1] != "lats"] + [("Barbell Row", "upper back", ["lats"])]
    assert _problems(days, _parsed(days, no_lats)) == ["Pull has no exercise for lats"]


def test_selection_cleans_secondaries():
    days = plan_days(SPLITS["ppl"], 3)
    picks = _picks_covering(days)
    row = [i for i, p in enumerate(picks[1]) if p[1] == "upper back"][0]
    picks[1][row] = ("Barbell Row", "upper back", ["upper back", "lats", "lats", "rear delts", "biceps", "lower back"])
    parse = MagicMock(return_value=_completion(_parsed(days, picks)))

    with patch("app.rag.exercise_selection.client.chat.completions.parse", parse):
        result = select_exercises(days, "hypertrophy", "Push/Pull/Legs")

    # primary dropped from its own secondaries, duplicates removed, capped at 3
    assert result[1][row] == ("Barbell Row", "upper back", ["lats", "rear delts", "biceps"])


@patch("app.routers.programs.select_exercises")
def test_generate_program_stores_secondaries(mock_select, db_session, user):
    def picks(days, goal, label):
        result = _picks_covering(days)
        result[0][0] = ("Barbell Bench Press", result[0][0][1], ["front delts", "triceps"])
        return result
    mock_select.side_effect = picks
    request = schemas.ProgramGenerateRequest(goal="hypertrophy", split="ppl", days_per_week=3)

    program = schemas.ProgramOut.model_validate(generate_program(request=request, db=db_session, current_user=user))

    first = program.mesocycles[0].day_templates[0].exercise_slots[0]
    assert (first.exercise_name, first.secondary_muscle_groups) == ("Barbell Bench Press", ["front delts", "triceps"])


def test_compounds_are_ordered_before_isolation():
    from app.rag.exercise_selection import _flatten

    day = plan_days(SPLITS["ppl"], 3)[0]  # Push: chest, front delts, side delts, triceps
    response = SimpleNamespace(
        chest=SimpleNamespace(exercise_name="Cable Fly", is_compound=False, secondary_muscle_groups=[]),
        front_delts=None,
        side_delts=SimpleNamespace(exercise_name="Lateral Raise", is_compound=False, secondary_muscle_groups=[]),
        triceps=SimpleNamespace(exercise_name="Pushdown", is_compound=False, secondary_muscle_groups=[]),
        extras=[SimpleNamespace(exercise_name="Bench Press", is_compound=True, muscle_group="chest",
                                secondary_muscle_groups=["front delts"])],
    )

    assert [p[0] for p in _flatten(day, response)] == ["Bench Press", "Cable Fly", "Lateral Raise", "Pushdown"]
