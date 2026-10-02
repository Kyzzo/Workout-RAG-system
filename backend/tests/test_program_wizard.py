# Program wizard: split -> planned days -> AI-picked exercises -> a full
# structure with placeholder weeks, ready for per-exercise generation.
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pydantic
import pytest
from fastapi import HTTPException

from app import models, schemas
from app.rag.exercise_selection import ExerciseSelectionError, _problems, _select_group, select_exercises
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


def _push_days():
    return [d for d in plan_days(SPLITS["ppl"], 6) if d.day_type == "Push"]  # Push 1, Push 2: one call


def test_selection_retries_once_when_a_muscle_group_is_missed():
    days = _push_days()
    good = _picks_covering(days)
    bad = [list(good[0]), good[1]]
    bad[0] = [p for p in bad[0] if p[1] != "triceps"] + [("Extra Press", "chest", [])]  # Push 1 skips triceps
    parse = MagicMock(side_effect=[_completion(_parsed(days, bad)), _completion(_parsed(days, good))])

    with patch("app.rag.exercise_selection.client.chat.completions.parse", parse):
        result = _select_group(days, "hypertrophy", "Push/Pull/Legs, 6 days per week")

    # same exercises (order: required targets first, then optional ones)
    assert [sorted(day) for day in result] == [sorted(day) for day in good]
    retry_prompt = parse.call_args_list[1].kwargs["messages"][-1]["content"]
    assert "Push 1 has no exercise for triceps" in retry_prompt


def test_selection_gives_up_after_one_retry():
    days = [d for d in plan_days(SPLITS["ppl"], 6) if d.day_type == "Pull"]
    bad = _picks_covering(days)
    bad[0] = [("Row", "upper back", ["lats", "rear delts"])] * 4  # Pull 1 never covers biceps
    parse = MagicMock(return_value=_completion(_parsed(days, bad)))

    with patch("app.rag.exercise_selection.client.chat.completions.parse", parse):
        with pytest.raises(ExerciseSelectionError):
            _select_group(days, "hypertrophy", "Push/Pull/Legs, 6 days per week")

    assert parse.call_count == 2


def test_selection_makes_one_call_per_day_type_and_keeps_day_order():
    days = plan_days(SPLITS["upper_lower"], 6)  # Upper 1, Lower 1, Upper 2, ...
    calls = []

    def fake_group(group_days, goal, description):
        calls.append([d.name for d in group_days])
        return [[(f"{d.name} lift", d.muscle_groups[0], [])] for d in group_days]

    with patch("app.rag.exercise_selection._select_group", side_effect=fake_group):
        result = select_exercises(days, "hypertrophy", "Upper/Lower")

    assert sorted(calls) == [["Lower 1", "Lower 2", "Lower 3"], ["Upper 1", "Upper 2", "Upper 3"]]
    assert [picks[0][0] for picks in result] == [f"{d.name} lift" for d in days]


def _enum_values(node, defs):
    # Enum values in a JSON schema with $refs expanded - how the structured-
    # outputs limit counts them (roughly: OpenAI's own count runs ~1.4x this
    # estimate, e.g. 1008 vs 714 for the old single-call 6-day Upper/Lower).
    if isinstance(node, dict):
        if "$ref" in node:
            return _enum_values(defs[node["$ref"].split("/")[-1]], defs)
        own = len(node.get("enum", [])) + (1 if "const" in node else 0)
        return own + sum(_enum_values(v, defs) for k, v in node.items() if k != "$defs")
    if isinstance(node, list):
        return sum(_enum_values(v, defs) for v in node)
    return 0


def test_every_selection_call_stays_well_under_the_enum_limit():
    from app.rag.exercise_selection import _response_schema

    for split in SPLITS.values():
        for n in split.allowed_days:
            by_type = {}
            for day in plan_days(split, n):
                by_type.setdefault(day.day_type, []).append(day)
            for group in by_type.values():
                schema = _response_schema(group).model_json_schema()
                # 1000 is OpenAI's limit; leave room for its higher count.
                assert _enum_values(schema, schema.get("$defs", {})) < 1000 / 1.5, (split.label, n)


def test_over_full_day_is_trimmed_not_rejected():
    from app.rag.exercise_selection import MAX_EXERCISES, _flatten

    day = [d for d in plan_days(SPLITS["torso_limbs"], 2) if d.day_type == "Torso"][0]
    def ex(name, compound=False, secondaries=()):
        return SimpleNamespace(exercise_name=name, is_compound=compound, secondary_muscle_groups=list(secondaries))
    fields = {g.replace(" ", "_"): ex(f"{g} lift") for g in day.muscle_groups}
    fields["chest"] = ex("Bench Press", compound=True, secondaries=["front delts", "triceps"])
    fields["extras"] = [
        SimpleNamespace(exercise_name=f"Extra {i}", is_compound=False, muscle_group="chest", secondary_muscle_groups=[])
        for i in range(3)
    ]

    picks = _flatten(day, SimpleNamespace(**fields))

    names = [p[0] for p in picks]
    assert len(picks) == MAX_EXERCISES
    assert "front delts lift" not in names  # already covered by the bench press as a secondary
    assert "lower back lift" in names  # not covered by anything else, so it stays


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
    days = [d for d in plan_days(SPLITS["ppl"], 6) if d.day_type == "Pull"]
    picks = _picks_covering(days)
    row = [i for i, p in enumerate(picks[0]) if p[1] == "upper back"][0]
    picks[0][row] = ("Barbell Row", "upper back", ["upper back", "lats", "lats", "rear delts", "biceps", "lower back"])
    parse = MagicMock(return_value=_completion(_parsed(days, picks)))

    with patch("app.rag.exercise_selection.client.chat.completions.parse", parse):
        result = _select_group(days, "hypertrophy", "Push/Pull/Legs, 6 days per week")

    # primary dropped from its own secondaries, duplicates removed, capped at 3
    assert result[0][row] == ("Barbell Row", "upper back", ["lats", "rear delts", "biceps"])


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


def test_unhandled_errors_reach_the_browser_with_cors_headers():
    # Without this, a crash became a 500 with no CORS headers and the UI
    # could only say "Failed to fetch".
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    from app.main import UnhandledErrorMiddleware

    app = FastAPI()
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    response = TestClient(app, raise_server_exceptions=False).get("/boom", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "RuntimeError" in response.json()["detail"]
