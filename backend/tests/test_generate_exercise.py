# Whole-block generation building blocks: one generation per exercise
# applied to every week, and chat history used only to resolve references.
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pydantic
import pytest
from fastapi import HTTPException

from app import models, schemas
from app.rag.chat_routing import route_chat_message
from app.routers.chat import send_chat_message
from app.routers.generation import generate_exercise


def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


def _slot_with_weeks(db_session, prescription, weeks):
    # The fixture's slot has only week 1; give it the rest of the block.
    for week in weeks:
        db_session.add(models.WeeklyPrescription(
            exercise_slot_id=prescription.exercise_slot_id, week_number=week, sets=0, reps="", load="",
        ))
    db_session.flush()
    return prescription.exercise_slot


def _gen(**fields):
    return MagicMock(side_effect=lambda *a, **k: (SimpleNamespace(**fields), _chunks(*fields["chunk_ids"])))


def _movement_gen(**values):
    """Fake generate_for_movement: one fixed value per field, cited to
    '<field>-1'. Records each (field, goal, movement, preference) asked."""
    calls = []

    def fake(field, goal, movement, preference="moderate"):
        calls.append((field, goal, movement, preference))
        return (
            SimpleNamespace(**{field: values[field]}, chunk_ids=[f"{field}-1"], grounding="fully_grounded"),
            _chunks(f"{field}-1"),
        )
    return fake, calls


def _add_slot(db_session, prescription, name, is_compound, weeks=(1,)):
    # Another exercise on the fixture's day, with placeholder weeks.
    slot = models.ExerciseSlot(
        day_template_id=prescription.exercise_slot.day_template_id, exercise_name=name,
        muscle_group="chest", is_compound=is_compound, order=9,
    )
    slot.weekly_prescriptions = [models.WeeklyPrescription(week_number=w, sets=0, reps="", load="") for w in weeks]
    db_session.add(slot)
    db_session.flush()
    return slot


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_hypertrophy_exercise_gets_reps_and_rir_for_its_movement_type_every_week(
    _verify, db_session, owner_and_prescription,
):
    user, prescription = owner_and_prescription  # hypertrophy
    slot = _slot_with_weeks(db_session, prescription, [2, 3])
    slot.is_compound = True
    for wp in slot.weekly_prescriptions:
        wp.sets = 3  # e.g. already split from the muscle's weekly volume
        wp.load = ""
    fake, calls = _movement_gen(reps="8-12", rir="1-2 RIR")

    with patch("app.routers.generation.generate_for_movement", side_effect=fake):
        result = generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    # Asked once per field for the movement type (not per exercise or week);
    # hypertrophy prescribes no load, and sets come from weekly volume.
    assert sorted(calls) == [("reps", "hypertrophy", "compound", "moderate"), ("rir", "hypertrophy", "compound", "moderate")]
    weeks = schemas.ExerciseSlotOut.model_validate(result).weekly_prescriptions
    assert [(wp.week_number, wp.sets, wp.reps, wp.load, wp.rir) for wp in weeks] == [
        (w, 3, "8-12", "", "1-2 RIR") for w in (1, 2, 3)
    ]
    for wp in weeks:
        assert [c.citation.title for c in wp.reps_citations] == ["paper-reps-1"]
        assert [c.citation.title for c in wp.rir_citations] == ["paper-rir-1"]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_strength_exercise_also_gets_a_percent_load(_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.exercise_slot.day_template.mesocycle.program.goal = "strength"
    slot = _slot_with_weeks(db_session, prescription, [2])
    slot.is_compound = True
    fake, _ = _movement_gen(reps="3-5", load="80% 1RM", rir="1-2 RIR")

    with patch("app.routers.generation.generate_for_movement", side_effect=fake):
        result = generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    weeks = schemas.ExerciseSlotOut.model_validate(result).weekly_prescriptions
    assert [(wp.reps, wp.load, wp.rir) for wp in weeks] == [("3-5", "80% 1RM", "1-2 RIR")] * 2
    assert all([c.citation.title for c in wp.load_citations] == ["paper-load-1"] for wp in weeks)


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_exercises_of_the_same_movement_type_share_one_answer(_verify, db_session, owner_and_prescription):
    # The cost fix: a second compound exercise reuses the stored, verified
    # answer (and its citations) instead of asking the model again; an
    # isolation exercise gets its own.
    user, prescription = owner_and_prescription
    bench = prescription.exercise_slot
    bench.is_compound = True
    incline = _add_slot(db_session, prescription, "Incline Press", is_compound=True)
    fly = _add_slot(db_session, prescription, "Cable Fly", is_compound=False)
    fake, calls = _movement_gen(reps="8-12", rir="1-2 RIR")

    with patch("app.routers.generation.generate_for_movement", side_effect=fake):
        for slot in (bench, incline, fly):
            generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    assert sorted(calls) == [
        ("reps", "hypertrophy", "compound", "moderate"), ("reps", "hypertrophy", "isolation", "moderate"),
        ("rir", "hypertrophy", "compound", "moderate"), ("rir", "hypertrophy", "isolation", "moderate"),
    ]
    reused = incline.weekly_prescriptions[0]
    assert (reused.reps, reused.rir) == ("8-12", "1-2 RIR")
    assert [c.citation.title for c in reused.reps_citations] == ["paper-reps-1"]


@patch("app.routers.generation.verify_citation", return_value="contradicted")
def test_unverified_answers_are_not_shared(_verify, db_session, owner_and_prescription):
    # An answer the judge couldn't support is never stored for reuse - the
    # next exercise asks again rather than inheriting an unlucky draw.
    user, prescription = owner_and_prescription
    prescription.exercise_slot.is_compound = True
    other = _add_slot(db_session, prescription, "Incline Press", is_compound=True)
    fake, calls = _movement_gen(reps="8-12", rir="1-2 RIR")

    with patch("app.routers.generation.generate_for_movement", side_effect=fake):
        generate_exercise(exercise_slot_id=prescription.exercise_slot_id, db=db_session, current_user=user)
        generate_exercise(exercise_slot_id=other.id, db=db_session, current_user=user)

    assert len(calls) == 8  # 2 fields x (attempt + retry) x 2 exercises
    assert db_session.query(models.SharedAnswer).count() == 0
    assert other.weekly_prescriptions[0].reps_grounding_note.startswith("This value could not be substantiated")


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_volume_preference_only_changes_the_rir_answer(_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.exercise_slot.is_compound = True
    fake, calls = _movement_gen(reps="8-12", rir="1-2 RIR")

    with patch("app.routers.generation.generate_for_movement", side_effect=fake):
        generate_exercise(exercise_slot_id=prescription.exercise_slot_id, db=db_session, current_user=user)
        prescription.exercise_slot.day_template.mesocycle.program.volume_preference = "minimal"
        generate_exercise(exercise_slot_id=prescription.exercise_slot_id, db=db_session, current_user=user)

    # reps reused across preferences; RIR asked again (minimal leans closer to failure)
    assert sorted(calls) == [
        ("reps", "hypertrophy", "compound", "moderate"),
        ("rir", "hypertrophy", "compound", "minimal"), ("rir", "hypertrophy", "compound", "moderate"),
    ]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_hand_added_exercise_is_classified_once(_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    assert prescription.exercise_slot.is_compound is None  # added by hand
    fake, calls = _movement_gen(reps="10-15", rir="0-1 RIR")

    with patch("app.routers.generation.classify_compound", return_value=False) as classify, \
            patch("app.routers.generation.generate_for_movement", side_effect=fake):
        generate_exercise(exercise_slot_id=prescription.exercise_slot_id, db=db_session, current_user=user)
        generate_exercise(exercise_slot_id=prescription.exercise_slot_id, db=db_session, current_user=user)

    classify.assert_called_once_with("Barbell Bench Press")
    assert prescription.exercise_slot.is_compound is False
    assert {movement for _, _, movement, _ in calls} == {"isolation"}


def test_generate_exercise_ownership_enforced(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription

    with pytest.raises(HTTPException) as exc_info:
        generate_exercise(exercise_slot_id=prescription.exercise_slot_id, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


# --- chat history -----------------------------------------------------------

@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_chat_passes_history_to_router(mock_route, mock_answer, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = SimpleNamespace(tool="answer_general_question", topic="t", field_id=None)
    mock_answer.return_value = (SimpleNamespace(statements=[], grounding="general_knowledge"), [])
    history = [schemas.ChatTurn(role="user", content="does failure training help?"),
               schemas.ChatTurn(role="assistant", content="Close to failure matters more.")]

    send_chat_message(
        request=schemas.ChatMessageRequest(message="what about legs?", history=history),
        db=db_session, current_user=user,
    )

    assert mock_route.call_args[0][2] == history


def test_router_sees_only_recent_history_as_reference_text():
    history = [schemas.ChatTurn(role="user", content=f"turn {i}") for i in range(10)]
    parse = MagicMock()
    parse.return_value.choices = [SimpleNamespace(message=SimpleNamespace(
        refusal=None, parsed=SimpleNamespace(field_id=None),
    ))]

    with patch("app.rag.chat_routing.client.chat.completions.parse", parse):
        route_chat_message("ok lower it", None, history)

    user_content = parse.call_args.kwargs["messages"][-1]["content"]
    assert "turn 3" not in user_content and "turn 4" in user_content and "turn 9" in user_content  # last 6 only
    assert user_content.index("Earlier conversation") < user_content.index("New message: ok lower it")


def test_chat_history_is_capped():
    with pytest.raises(pydantic.ValidationError):
        schemas.ChatMessageRequest(message="m", history=[{"role": "user", "content": "x"}] * 21)
