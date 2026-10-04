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


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_intensity_load")
@patch("app.routers.generation.generate_volume_sets")
def test_hypertrophy_exercise_gets_reps_and_rir_once_for_every_week(
    mock_sets, mock_load, _verify, db_session, owner_and_prescription,
):
    user, prescription = owner_and_prescription  # hypertrophy
    slot = _slot_with_weeks(db_session, prescription, [2, 3])
    for wp in slot.weekly_prescriptions:
        wp.sets = 3  # e.g. already split from the muscle's weekly volume
        wp.load = ""
    reps = _gen(reps="8-12", chunk_ids=["rep-1"], grounding="fully_grounded")
    rir = _gen(rir="1-2 RIR", chunk_ids=["rir-1"], grounding="fully_grounded")

    with patch("app.routers.generation.generate_reps", reps), patch("app.routers.generation.generate_rir", rir):
        result = generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    # Sets come from the muscle's weekly volume; hypertrophy prescribes no load.
    mock_sets.assert_not_called()
    mock_load.assert_not_called()
    reps.assert_called_once()  # once for the exercise, not once per week
    rir.assert_called_once()
    assert reps.call_args.args[2] == slot.exercise_name  # asked per exercise
    weeks = schemas.ExerciseSlotOut.model_validate(result).weekly_prescriptions
    assert [(wp.week_number, wp.sets, wp.reps, wp.load, wp.rir) for wp in weeks] == [
        (w, 3, "8-12", "", "1-2 RIR") for w in (1, 2, 3)
    ]
    for wp in weeks:
        assert [c.citation.title for c in wp.reps_citations] == ["paper-rep-1"]
        assert [c.citation.title for c in wp.rir_citations] == ["paper-rir-1"]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_intensity_load")
def test_strength_exercise_also_gets_a_percent_load(mock_load, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.exercise_slot.day_template.mesocycle.program.goal = "strength"
    slot = _slot_with_weeks(db_session, prescription, [2])
    mock_load.return_value = (SimpleNamespace(load="80% 1RM", chunk_ids=["i-1"], grounding="fully_grounded"), _chunks("i-1"))
    reps = _gen(reps="3-5", chunk_ids=["rep-1"], grounding="fully_grounded")
    rir = _gen(rir="1-2 RIR", chunk_ids=["rir-1"], grounding="fully_grounded")

    with patch("app.routers.generation.generate_reps", reps), patch("app.routers.generation.generate_rir", rir):
        result = generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    weeks = schemas.ExerciseSlotOut.model_validate(result).weekly_prescriptions
    assert [(wp.reps, wp.load, wp.rir) for wp in weeks] == [("3-5", "80% 1RM", "1-2 RIR")] * 2
    assert all([c.citation.title for c in wp.load_citations] == ["paper-i-1"] for wp in weeks)


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
