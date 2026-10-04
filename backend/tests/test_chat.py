from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.rag.verification import STATEMENT_JUDGE
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


def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


def _answer(*statements, grounding="fully_grounded"):
    # A statement-structured answer: each (text, [source ids]).
    return SimpleNamespace(
        statements=[SimpleNamespace(text=t, sources=list(src)) for t, src in statements],
        grounding=grounding,
    )


def _cite_stored(db_session, prescription, field, title, snippet, status):
    citation = models.Citation(title=title, snippet=snippet, qdrant_point_id=f"chunk-{title}")
    db_session.add(citation)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=prescription.id, citation_id=citation.id, field=field, verification_status=status,
    ))
    db_session.flush()
    return citation


@patch("app.routers.chat.answer_prescription_discussion")
@patch("app.routers.chat.route_chat_message")
def test_structural_context_field_id_overrides_model(mock_route, mock_answer, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id, question="why is this?")
    mock_answer.return_value = _answer(("It's 8-10 reps.", ["prescription"]))

    request = schemas.ChatMessageRequest(message="why is this?", field_id=prescription.id)
    send_chat_message(request=request, db=db_session, current_user=user)

    # The anchored field_id is what reaches the router (which then enforces
    # it over anything the model reports - see chat_routing.py).
    mock_route.assert_called_once_with("why is this?", prescription.id, [])


@patch("app.routers.chat.verify_citation", return_value="primary_support")
@patch("app.routers.chat.answer_prescription_discussion")
@patch("app.routers.chat.route_chat_message")
def test_discuss_uses_only_stored_supported_citations(mock_route, mock_answer, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    good = _cite_stored(db_session, prescription, "sets", "Some Paper", "an excerpt", "primary_support")
    _cite_stored(db_session, prescription, "sets", "Unrelated Paper", "irrelevant", "contradicted")
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id, question="why 3 sets?")
    mock_answer.return_value = _answer(("The cited study supports this weekly volume.", [f"sets-{good.id}"]))

    result = send_chat_message(
        request=schemas.ChatMessageRequest(message="why 3 sets?", field_id=prescription.id),
        db=db_session, current_user=user,
    )

    # Only the supported excerpt is offered to the answer, labeled with its value
    excerpts = mock_answer.call_args.args[2]
    assert [(e["text"], e["field"]) for e in excerpts] == [("an excerpt", "sets")]
    assert result.answer == "The cited study supports this weekly volume. [1]"
    assert [(c.title, c.field) for c in result.citations] == [("Some Paper", "sets")]


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_prescription_discussion")
@patch("app.routers.chat.route_chat_message")
def test_discuss_statement_that_misrepresents_its_excerpt_is_removed(
    mock_route, mock_answer, mock_verify, db_session, owner_and_prescription,
):
    # Rephrasing a verified excerpt can still misrepresent it, so discuss
    # answers are checked statement by statement too.
    user, prescription = owner_and_prescription
    cite = _cite_stored(db_session, prescription, "sets", "Paper", "similar growth at 12 and 24 sets", "primary_support")
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id, question="why?")
    mock_answer.return_value = _answer(
        ("Your plan has 3 sets per session.", ["prescription"]),
        ("24 sets is optimal for growth.", [f"sets-{cite.id}"]),
    )
    mock_verify.return_value = "contradicted"

    result = send_chat_message(
        request=schemas.ChatMessageRequest(message="why?", field_id=prescription.id), db=db_session, current_user=user,
    )

    assert result.answer == "Your plan has 3 sets per session."  # app-data statement kept, overstatement dropped
    assert result.citations == []
    assert "1 statement was removed" in result.grounding_note


@patch("app.routers.chat.route_chat_message")
def test_discuss_prescription_ownership_enforced(mock_route, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mock_route.return_value = _route("discuss_prescription", field_id=prescription.id, question="why?")

    request = schemas.ChatMessageRequest(message="why?", field_id=prescription.id)
    with pytest.raises(HTTPException) as exc_info:
        send_chat_message(request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_answer_is_built_only_from_verified_statements(mock_route, mock_answer, mock_verify, db_session, owner_and_prescription):
    # The reported bug: an unverified sentence merged a strength trend in
    # direct sets with a hypertrophy threshold in fractional sets into a
    # range neither study states. Every statement is now judged on its own.
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="optimal weekly sets?")
    mock_answer.return_value = (
        _answer(
            ("No detectable superiority beyond ~31 fractional sets per week for hypertrophy.", ["remmert"]),
            ("12, 18 and 24 weekly quad sets produced similar growth in trained lifters.", ["aube"]),
            ("So 18 to 31 sets per week is optimal for hypertrophy.", ["aube", "remmert"]),
        ),
        _chunks("remmert", "aube"),
    )
    supported = {
        "No detectable superiority beyond ~31 fractional sets per week for hypertrophy.": "primary_support",
        "12, 18 and 24 weekly quad sets produced similar growth in trained lifters.": "primary_support",
    }
    mock_verify.side_effect = lambda q, text, chunk, **kwargs: supported.get(text, "contradicted")

    result = send_chat_message(
        request=schemas.ChatMessageRequest(message="optimal weekly sets?"), db=db_session, current_user=user,
    )

    assert result.answer == (
        "No detectable superiority beyond ~31 fractional sets per week for hypertrophy. [1] "
        "12, 18 and 24 weekly quad sets produced similar growth in trained lifters. [2]"
    )
    assert [c.title for c in result.citations] == ["paper-remmert", "paper-aube"]
    assert "1 statement was removed" in result.grounding_note
    assert db_session.query(models.Citation).filter(models.Citation.title == "paper-remmert").count() == 0  # not persisted
    # prose statements get the strict judge, not the fast one used for bare values
    assert {call.kwargs["judge"] for call in mock_verify.call_args_list} == {STATEMENT_JUDGE}


@patch("app.routers.chat.verify_citation", return_value="primary_support")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_uncited_statements_are_never_shown(mock_route, mock_answer, _verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="t")
    mock_answer.return_value = (
        _answer(("Cited claim.", ["c1"]), ("Uncited general claim.", [])),
        _chunks("c1"),
    )

    result = send_chat_message(request=schemas.ChatMessageRequest(message="t"), db=db_session, current_user=user)

    assert result.answer == "Cited claim. [1]"


@patch("app.routers.chat.verify_citation", return_value="contradicted")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_question_retries_when_nothing_verifies(mock_route, mock_answer, _verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="t")
    mock_answer.return_value = (_answer(("Claim.", ["c1"])), _chunks("c1"))

    result = send_chat_message(request=schemas.ChatMessageRequest(message="t"), db=db_session, current_user=user)

    assert mock_answer.call_count == 2  # one bounded retry
    # nothing verified -> no unverified prose fallback, said plainly
    assert result.answer.startswith("The research in this app's corpus doesn't support")
    assert result.citations == []
    assert result.grounding_note == "This value could not be substantiated by the current research corpus."


@patch("app.routers.chat.verify_citation")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_general_question_general_knowledge_skips_retry(mock_route, mock_answer, mock_verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="t")
    mock_answer.return_value = (_answer(grounding="general_knowledge"), _chunks("c1"))

    result = send_chat_message(request=schemas.ChatMessageRequest(message="t"), db=db_session, current_user=user)

    mock_answer.assert_called_once()
    mock_verify.assert_not_called()
    assert result.grounding_note == "This is a general estimate based on established training principles, not a specific study."


def _with_summary(parsed, text, sources):
    parsed.summary = SimpleNamespace(text=text, sources=list(sources))
    return parsed


@patch("app.routers.chat.verify_summary", return_value=True)
@patch("app.routers.chat.verify_citation", return_value="primary_support")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_verified_summary_leads_the_answer(mock_route, mock_answer, _verify, mock_summary, db_session, owner_and_prescription):
    # The practical answer may synthesize across sources, so it's judged
    # against all of them together, then shown first with the evidence after.
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="how many sets?")
    mock_answer.return_value = (
        _with_summary(
            _answer(("Growth rose with weekly sets.", ["a"]), ("12-24 sets gave similar growth.", ["b"])),
            "Roughly 10-20 weekly sets per muscle suits most lifters.", ["a", "b"],
        ),
        _chunks("a", "b"),
    )

    result = send_chat_message(request=schemas.ChatMessageRequest(message="how many sets?"), db=db_session, current_user=user)

    assert result.answer == (
        "Roughly 10-20 weekly sets per muscle suits most lifters. [1][2]\n\n"
        "Growth rose with weekly sets. [1] 12-24 sets gave similar growth. [2]"
    )
    assert mock_summary.call_args.args[2] == ["excerpt for a", "excerpt for b"]  # judged against every source at once
    assert result.grounding_note is None


@patch("app.routers.chat.verify_summary", return_value=False)
@patch("app.routers.chat.verify_citation", return_value="primary_support")
@patch("app.routers.chat.answer_general_question")
@patch("app.routers.chat.route_chat_message")
def test_rejected_summary_is_dropped_and_counted(mock_route, mock_answer, _verify, _summary, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    mock_route.return_value = _route("answer_general_question", topic="t")
    mock_answer.return_value = (
        _with_summary(_answer(("Cited claim.", ["a"])), "18-31 sets is optimal.", ["a"]),
        _chunks("a"),
    )

    result = send_chat_message(request=schemas.ChatMessageRequest(message="t"), db=db_session, current_user=user)

    assert result.answer == "Cited claim. [1]"
    assert "1 statement was removed" in result.grounding_note
