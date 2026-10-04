# Mechanical rules get citations the same way generated values do: a fixed
# claim, checked against retrieved research by the verification judge, with
# only accepted excerpts shown - cached, and re-run on refresh.
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models
from app.rag.rule_justifications import NO_SUPPORT_NOTE, justify_rule
from app.routers.programs import get_rule_justification


def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


def _clear(db_session):
    # ORM delete so the cached rule's citation rows cascade with it (the dev
    # database may already hold a real cached result; the test transaction
    # rolls this back afterwards).
    for record in db_session.query(models.RuleJustification).filter_by(rule_key="even_session_split"):
        db_session.delete(record)
    db_session.flush()


@patch("app.rag.rule_justifications.judge_citation")
@patch("app.rag.rule_justifications._retrieve_chunks")
def test_rule_shows_only_judge_accepted_excerpts_and_is_cached(mock_retrieve, mock_judge, db_session):
    _clear(db_session)
    mock_retrieve.side_effect = lambda query, category: _chunks(f"{category}-1", "shared")
    verdicts = {"excerpt for volume-1": "primary_support", "excerpt for frequency-1": "contradicted",
                "excerpt for shared": "contextual_support"}
    mock_judge.side_effect = lambda q, claim, text, judge: SimpleNamespace(outcome=verdicts[text], reasoning="")

    first = justify_rule(db_session, "even_session_split")
    calls_after_first = mock_judge.call_count
    second = justify_rule(db_session, "even_session_split")

    assert sorted(c.citation.title for c in first.supporting_citations) == ["paper-shared", "paper-volume-1"]
    assert first.grounding_note is None
    assert calls_after_first == 3  # the chunk found by both searches is judged once
    assert mock_judge.call_count == 3 and second.id == first.id  # cached, no re-judging


@patch("app.rag.rule_justifications.judge_citation")
@patch("app.rag.rule_justifications._retrieve_chunks")
def test_refresh_rejudges_and_unsupported_rules_say_so(mock_retrieve, mock_judge, db_session):
    _clear(db_session)
    mock_retrieve.side_effect = lambda query, category: _chunks(f"{category}-1")
    mock_judge.return_value = SimpleNamespace(outcome="primary_support", reasoning="")
    justify_rule(db_session, "even_session_split")

    mock_judge.return_value = SimpleNamespace(outcome="contradicted", reasoning="")
    refreshed = justify_rule(db_session, "even_session_split", refresh=True)

    assert refreshed.supporting_citations == []
    assert refreshed.grounding_note == NO_SUPPORT_NOTE
    assert db_session.query(models.RuleCitation).filter_by(rule_id=refreshed.id).count() == 2  # replaced, not stacked


def test_unknown_rule_is_404(db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    with pytest.raises(HTTPException) as exc_info:
        get_rule_justification(rule_key="nope", db=db_session, current_user=user)
    assert exc_info.value.status_code == 404



@patch("app.rag.rule_justifications.judge_citation")
@patch("app.rag.rule_justifications._retrieve_chunks")
def test_same_excerpt_from_a_double_ingested_paper_is_judged_once(mock_retrieve, mock_judge, db_session):
    _clear(db_session)
    # the same paper ingested as volume AND frequency: identical text, different ids
    mock_retrieve.side_effect = lambda query, category: [
        {"id": f"{category}-copy", "text": "per-session volume shows diminishing returns", "source": f"paper-{category}"}
    ]
    mock_judge.return_value = SimpleNamespace(outcome="primary_support", reasoning="")

    record = justify_rule(db_session, "even_session_split")

    assert mock_judge.call_count == 1
    assert len(record.supporting_citations) == 1
