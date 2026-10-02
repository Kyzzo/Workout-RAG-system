from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.chat import send_chat_message


def _route(tool, **kwargs):
    return SimpleNamespace(
        tool=tool,
        field_id=kwargs.get("field_id"),
        target_field=kwargs.get("target_field"),
        adjustment_kind=kwargs.get("adjustment_kind"),
        requested_value=kwargs.get("requested_value"),
        requested_change=kwargs.get("requested_change"),
        question=kwargs.get("question"),
        topic=kwargs.get("topic"),
    )


def _fake_result(**fields):
    return SimpleNamespace(**fields)


def _fake_chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


def _fake_citation(chunk_id, supports):
    return SimpleNamespace(chunk_id=chunk_id, supports=supports)


@patch("app.routers.chat.route_chat_message")
@patch("app.routers.chat._generate_and_persist")
def test_adjust_prescription_reuses_generation_pipeline(mock_persist, mock_route, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_route.return_value = _route("adjust_prescription", field_id=prescription.id, target_field="sets")
    prescription.sets = 14
    mock_persist.return_value = prescription

    request = schemas.ChatMessageRequest(message="add more volume for chest")
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.mode == "adjust_prescription"
    assert result.prescription.sets == 14
    # Dispatched through the shared persist/retry/citation-replace logic
    # already proven for the direct REST endpoints, not a separate write path.
    mock_persist.assert_called_once()
    called_field_name = mock_persist.call_args[0][4]
    assert called_field_name == "sets"


@patch("app.routers.chat.route_chat_message")
def test_adjust_prescription_requires_a_field(mock_route, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("adjust_prescription", field_id=None, target_field="sets")

    request = schemas.ChatMessageRequest(message="add more volume")
    with pytest.raises(HTTPException) as exc_info:
        send_chat_message(request=request, db=db_session, current_user=user)

    assert exc_info.value.status_code == 400


@patch("app.routers.chat.route_chat_message")
def test_adjust_prescription_ownership_enforced(mock_route, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mock_route.return_value = _route("adjust_prescription", field_id=prescription.id, target_field="sets")

    request = schemas.ChatMessageRequest(message="add more volume")
    with pytest.raises(HTTPException) as exc_info:
        send_chat_message(request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


@patch("app.routers.chat.answer_prescription_discussion")
@patch("app.routers.chat.route_chat_message")
def test_structural_context_field_id_overrides_model(mock_route, mock_answer, db_session, owner_and_prescription):
    # route_chat_message itself is responsible for pinning field_id when
    # known_field_id was passed in (chat_routing.py) - this test confirms
    # the endpoint actually PASSES the anchored field_id through, not that
    # it re-derives the override itself (that's chat_routing's own job).
    user, prescription = owner_and_prescription
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id)
    mock_answer.return_value = "An answer."

    request = schemas.ChatMessageRequest(message="why is this?", field_id=prescription.id)
    send_chat_message(request=request, db=db_session, current_user=user)

    mock_route.assert_called_once_with("why is this?", prescription.id, [])


@patch("app.routers.chat.answer_prescription_discussion")
@patch("app.routers.chat.route_chat_message")
def test_discuss_prescription_reads_stored_citations_only(mock_route, mock_answer, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    citation = models.Citation(title="Some Paper", snippet="an excerpt", qdrant_point_id="chunk-1")
    db_session.add(citation)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=prescription.id, citation_id=citation.id, field="sets", verification_status="primary_support",
    ))
    # A contradicted row for the same prescription should never surface as
    # if it were valid evidence (datamodel.txt's PrescriptionCitation
    # display rule).
    other_citation = models.Citation(title="Unrelated Paper", snippet="irrelevant", qdrant_point_id="chunk-2")
    db_session.add(other_citation)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=prescription.id, citation_id=other_citation.id, field="sets", verification_status="contradicted",
    ))
    db_session.flush()

    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id, question="why is this 8-10 reps?")
    mock_answer.return_value = "Because the cited study reports 8-10 reps for this goal."
    request = schemas.ChatMessageRequest(message="why is this 8-10 reps?", field_id=prescription.id)
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.mode == "discuss_prescription"
    assert result.answer == "Because the cited study reports 8-10 reps for this goal."
    assert len(result.citations) == 1
    assert result.citations[0].title == "Some Paper"
    # Only the SUPPORTED citation's snippet is passed as grounding context -
    # the contradicted one never reaches the answer either.
    passed_question, _passed_summary, passed_snippets = mock_answer.call_args[0]
    assert passed_question == "why is this 8-10 reps?"
    # ...and is labeled with the value it backs.
    assert passed_snippets == ["[supports the sets value] an excerpt"]


@patch("app.routers.chat.answer_prescription_discussion")
@patch("app.routers.chat.route_chat_message")
def test_discuss_prescription_actually_answers_the_question(mock_route, mock_answer, db_session, owner_and_prescription):
    # The real bug this test guards against: discuss_prescription used to
    # ignore the user's question entirely and just echo back the raw stored
    # prescription data, no matter what was actually asked.
    user, prescription = owner_and_prescription
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id, question="would you recommend reducing it?")
    mock_answer.return_value = "Given the cited range, reducing it slightly would still be well-supported."

    request = schemas.ChatMessageRequest(message="would you recommend reducing it?", field_id=prescription.id)
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.answer == "Given the cited range, reducing it slightly would still be well-supported."
    mock_answer.assert_called_once()


@patch("app.routers.chat.route_chat_message")
def test_discuss_prescription_ownership_enforced(mock_route, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id)

    request = schemas.ChatMessageRequest(message="why is this?")
    with pytest.raises(HTTPException) as exc_info:
        send_chat_message(request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_question_returns_response_level_citations_without_persisting(
    mock_route, mock_answer, mock_verify, db_session, owner_and_prescription
):
    user, prescription = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="training to failure")
    mock_answer.return_value = (
        _fake_result(
            answer="Training to failure isn't required for hypertrophy.",
            citations=[_fake_citation("chunk-1", "Training to failure isn't required for hypertrophy.")],
            grounding="fully_grounded",
        ),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    request = schemas.ChatMessageRequest(message="what does research say about training to failure?")
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.mode == "answer_general_question"
    assert result.answer == "Training to failure isn't required for hypertrophy."
    assert result.grounding_note is None
    assert len(result.citations) == 1
    assert result.citations[0].title == "paper-chunk-1"
    mock_answer.assert_called_once()  # no retry needed - it was supported on the first try
    # Response-level Q&A never writes a PrescriptionCitation row - it isn't
    # tied to any one WeeklyPrescription. Scoped to this fixture's own
    # prescription rather than the whole table, since the real dev DB (this
    # test still runs against it, just inside a rolled-back transaction -
    # see conftest.py) can have unrelated committed rows from other sessions.
    assert db_session.query(models.PrescriptionCitation).filter(
        models.PrescriptionCitation.prescription_id == prescription.id
    ).count() == 0


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_question_drops_a_citation_misattributed_to_a_claim_it_doesnt_support(
    mock_route, mock_answer, mock_verify, db_session, owner_and_prescription
):
    # The real bug this whole mode-3-judge extension exists to catch: a
    # chunk that's a genuine, retrieved, real citation - just cited for a
    # claim it doesn't actually back (e.g. a dataset-composition stat used
    # to imply an efficacy finding). The chunk should be dropped from what's
    # shown as evidence even though the answer itself still renders.
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="training to failure")
    mock_answer.return_value = (
        _fake_result(
            answer="Training to failure leads to greater gains. 78% of studies used it.",
            citations=[
                _fake_citation("chunk-good", "Training to failure leads to greater gains."),
                _fake_citation("chunk-bad", "78% of studies used it."),
            ],
            grounding="fully_grounded",
        ),
        _fake_chunks("chunk-good", "chunk-bad"),
    )
    # First attempt: one real support, one misattribution (contradicted) -
    # any_supported is True overall (chunk-good passed), so no retry fires.
    mock_verify.side_effect = ["primary_support", "contradicted"]

    request = schemas.ChatMessageRequest(message="what does research say about training to failure?")
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.grounding_note is None  # overall answer still has real support
    assert len(result.citations) == 1
    assert result.citations[0].title == "paper-chunk-good"
    mock_answer.assert_called_once()


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_question_retries_when_nothing_verifies(mock_route, mock_answer, mock_verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="training to failure")
    first_attempt = (
        _fake_result(
            answer="First attempt.",
            citations=[_fake_citation("chunk-1", "First attempt.")],
            grounding="fully_grounded",
        ),
        _fake_chunks("chunk-1"),
    )
    second_attempt = (
        _fake_result(
            answer="Second attempt.",
            citations=[_fake_citation("chunk-2", "Second attempt.")],
            grounding="fully_grounded",
        ),
        _fake_chunks("chunk-2"),
    )
    mock_answer.side_effect = [first_attempt, second_attempt]
    mock_verify.side_effect = ["contradicted", "primary_support"]

    request = schemas.ChatMessageRequest(message="what does research say about training to failure?")
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.answer == "Second attempt."
    assert result.grounding_note is None
    assert mock_answer.call_count == 2


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_question_general_knowledge_skips_retry(mock_route, mock_answer, mock_verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="training to failure")
    mock_answer.return_value = (
        _fake_result(answer="An honest estimate.", citations=[], grounding="general_knowledge"),
        [],
    )

    request = schemas.ChatMessageRequest(message="what does research say about training to failure?")
    result = send_chat_message(request=request, db=db_session, current_user=user)

    assert result.grounding_note == "This is a general estimate based on established training principles, not a specific study."
    assert result.citations == []
    mock_answer.assert_called_once()
    mock_verify.assert_not_called()
