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


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_intensity_load")
@patch("app.routers.generation.generate_volume_sets")
def test_generate_exercise_generates_load_once_for_every_week_and_leaves_sets(
    mock_sets, mock_load, mock_verify, db_session, owner_and_prescription,
):
    user, prescription = owner_and_prescription
    slot = _slot_with_weeks(db_session, prescription, [2, 3])
    for wp in slot.weekly_prescriptions:
        wp.sets = 3  # e.g. already split from the muscle's weekly volume
    mock_load.return_value = (SimpleNamespace(load="70% 1RM", chunk_ids=["i-1"], grounding="fully_grounded"), _chunks("i-1"))
    mock_verify.return_value = "primary_support"

    result = generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    # Sets come from the muscle's weekly volume now, never from here.
    mock_sets.assert_not_called()
    mock_load.assert_called_once()  # once for the exercise, not once per week
    weeks = schemas.ExerciseSlotOut.model_validate(result).weekly_prescriptions
    assert [(wp.week_number, wp.sets, wp.load) for wp in weeks] == [(1, 3, "70% 1RM"), (2, 3, "70% 1RM"), (3, 3, "70% 1RM")]
    for wp in weeks:
        assert [c.citation.title for c in wp.load_citations] == ["paper-i-1"]


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_intensity_load")
@patch("app.routers.generation.generate_volume_sets")
def test_generate_exercise_replaces_previous_week_citations(
    mock_sets, mock_load, mock_verify, db_session, owner_and_prescription,
):
    user, prescription = owner_and_prescription
    slot = _slot_with_weeks(db_session, prescription, [2])
    week2 = next(wp for wp in slot.weekly_prescriptions if wp.week_number == 2)
    stale = models.Citation(title="stale", snippet="s", qdrant_point_id="stale-1")
    db_session.add(stale)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=week2.id, citation_id=stale.id, field="load", verification_status="primary_support",
    ))
    db_session.flush()
    mock_load.return_value = (SimpleNamespace(load="RPE 8", chunk_ids=["i-1"], grounding="fully_grounded"), _chunks("i-1"))
    mock_verify.return_value = "primary_support"

    generate_exercise(exercise_slot_id=slot.id, db=db_session, current_user=user)

    db_session.expire_all()
    titles = [c.citation.title for c in db_session.get(models.WeeklyPrescription, week2.id).load_citations]
    assert titles == ["paper-i-1"]


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
    mock_answer.return_value = (SimpleNamespace(answer="a", citations=[], grounding="general_knowledge"), [])
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
