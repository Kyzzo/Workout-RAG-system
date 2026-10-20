# Suggested general questions are answered once and reused (verified
# answers only); the streamed chat reports its stages, then the result.
import json
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import models, schemas
from app.auth import get_current_user
from app.main import app
from app.routers import chat
from app.routers.chat import send_chat_message

PRESET = "How close to failure should I train?"


def _answer(*statements, grounding="fully_grounded"):
    return SimpleNamespace(
        statements=[SimpleNamespace(text=t, sources=list(src)) for t, src in statements],
        grounding=grounding,
    )


def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


@patch("app.routers.chat.verify_citation", return_value="primary_support")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_preset_question_is_answered_once_then_reused(mock_route, mock_answer, _verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_answer.return_value = (_answer(("Stop 0-3 reps short of failure.", ["a"])), _chunks("a"))

    # Different spacing and case still match the suggestion.
    first = send_chat_message(request=schemas.ChatMessageRequest(message=PRESET), db=db_session, current_user=user)
    second = send_chat_message(
        request=schemas.ChatMessageRequest(message="  how close to FAILURE should i train?"), db=db_session, current_user=user,
    )

    assert mock_answer.call_count == 1  # the second came from the store
    assert second == first
    mock_route.assert_not_called()  # a suggested general question needs no routing
    stored = db_session.query(models.SharedAnswer).filter(models.SharedAnswer.field == "chat").one()
    assert stored.key.endswith("|chat|how close to failure should i train?")


@patch("app.routers.chat.verify_citation", return_value="contradicted")
@patch("app.routers.chat.answer_general_question")
def test_unverified_preset_answer_is_not_stored(mock_answer, _verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_answer.return_value = (_answer(("Unsupported claim.", ["a"])), _chunks("a"))

    send_chat_message(request=schemas.ChatMessageRequest(message=PRESET), db=db_session, current_user=user)

    assert db_session.query(models.SharedAnswer).filter(models.SharedAnswer.field == "chat").count() == 0


@patch("app.routers.chat._handle_discuss")
@patch("app.routers.chat.route_chat_message")
def test_preset_text_about_an_exercise_is_routed_as_usual(mock_route, mock_discuss, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_route.return_value = SimpleNamespace(tool="discuss_prescription", target_field=None)
    mock_discuss.return_value = schemas.ChatResponse(mode="discuss_prescription", answer="x", citations=[])

    send_chat_message(
        request=schemas.ChatMessageRequest(message=PRESET, field_id=prescription.id), db=db_session, current_user=user,
    )

    mock_route.assert_called_once()


@patch("app.routers.chat.verify_citation", return_value="primary_support")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_stream_reports_stages_then_the_result(
    mock_route, mock_answer, _verify, db_session, owner_and_prescription, monkeypatch,
):
    user, _ = owner_and_prescription
    mock_route.return_value = SimpleNamespace(tool="answer_general_question", topic="sets?", field_id=None)
    mock_answer.return_value = (_answer(("A claim.", ["a"]), ("Another.", ["b"])), _chunks("a", "b"))
    # The stream's worker uses the test's session (and mustn't close it).
    monkeypatch.setattr(chat, "_session_factory", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).post("/chat/message/stream", json={"message": "how many sets?"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    events = [json.loads(line) for line in response.text.splitlines()]
    stages = [e["label"] for e in events if e["type"] == "stage"]
    assert stages == ["Understanding your question", "Checking 2 statements against their sources"]
    assert events[-1]["type"] == "result"
    assert events[-1]["response"]["answer"].endswith("\n\nA claim. [1] Another. [2]")


@patch("app.routers.chat.route_chat_message")
def test_stream_reports_a_request_error(mock_route, db_session, owner_and_prescription, monkeypatch):
    user, _ = owner_and_prescription
    # An adjust with no exercise anchored is refused with a 400.
    mock_route.return_value = SimpleNamespace(tool="adjust_prescription", target_field="sets", field_id=None)
    monkeypatch.setattr(chat, "_session_factory", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).post("/chat/message/stream", json={"message": "add a set"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    last = json.loads(response.text.splitlines()[-1])
    assert last["type"] == "error" and last["status"] == 400
