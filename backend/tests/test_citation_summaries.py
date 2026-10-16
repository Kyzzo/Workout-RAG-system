# Plain-language source summaries: written and checked once per citation,
# stored only when the judge finds the excerpt states them directly.
from unittest.mock import patch

from app import models
from app.rag.citation_summaries import checked_summary
from app.routers import citations
from app.routers.citations import get_citation_summary


def _citation(db_session):
    citation = models.Citation(
        title="Pelland et al. 2025 · meta-analysis", snippet="Growth rose with weekly sets.", qdrant_point_id="c-1",
    )
    db_session.add(citation)
    db_session.flush()
    return citation


@patch("app.rag.citation_summaries.verify_citation", return_value="primary_support")
@patch("app.rag.citation_summaries.write_summary", return_value="More weekly sets led to more muscle growth.")
def test_summary_is_written_checked_and_stored_once(mock_write, _verify, db_session, owner_and_prescription):
    user, _ = owner_and_prescription
    citation = _citation(db_session)

    first = get_citation_summary(citation.id, db_session, user)
    second = get_citation_summary(citation.id, db_session, user)

    assert first.summary == second.summary == "More weekly sets led to more muscle growth."
    assert mock_write.call_count == 1  # the second came from the store


@patch("app.rag.citation_summaries.verify_citation", return_value="contradicted")
@patch("app.rag.citation_summaries.write_summary", return_value="No difference in growth.")
def test_summary_the_judge_rejects_is_never_shown_or_stored(mock_write, _verify, db_session, owner_and_prescription, monkeypatch):
    user, _ = owner_and_prescription
    monkeypatch.setattr(citations, "_failed", set())
    citation = _citation(db_session)

    assert get_citation_summary(citation.id, db_session, user).summary is None
    assert mock_write.call_count == 2  # one retry
    assert db_session.query(models.SharedAnswer).filter(models.SharedAnswer.field == "citation_summary").count() == 0
    get_citation_summary(citation.id, db_session, user)
    assert mock_write.call_count == 2  # a failed citation isn't paid for again


def _two_citations(db_session):
    first = _citation(db_session)
    second = models.Citation(title="Aube et al. 2022 · randomized trial", snippet="12-24 sets: similar growth.",
                             qdrant_point_id="c-2")
    db_session.add(second)
    db_session.flush()
    return first, second


@patch("app.rag.citation_summaries.verify_summary", return_value=True)
@patch("app.rag.citation_summaries.write_panel_summary", return_value="More weekly sets built more muscle.")
def test_panel_summary_is_written_once_per_question_and_citations(mock_write, _verify, db_session,
                                                                  owner_and_prescription):
    user, _ = owner_and_prescription
    a, b = _two_citations(db_session)

    first = citations.get_panel_summary(
        citations.PanelSummaryIn(question="Why 12 weekly sets for chest?", citation_ids=[a.id, b.id]), db_session, user,
    )
    # Same citations in another order, same question with other spacing and
    # case: the same stored summary.
    second = citations.get_panel_summary(
        citations.PanelSummaryIn(question="why  12 weekly sets for chest?", citation_ids=[b.id, a.id]), db_session, user,
    )

    assert first.summary == second.summary == "More weekly sets built more muscle."
    assert mock_write.call_count == 1
    excerpts = mock_write.call_args.args[1]
    assert [title for title, _ in excerpts] == [a.title, b.title]  # every citation, in a fixed order


@patch("app.rag.citation_summaries.verify_summary", return_value=False)
@patch("app.rag.citation_summaries.write_panel_summary", return_value="18 sets is optimal.")
def test_panel_summary_the_judge_rejects_is_never_stored(mock_write, _verify, db_session, owner_and_prescription,
                                                         monkeypatch):
    user, _ = owner_and_prescription
    monkeypatch.setattr(citations, "_failed", set())
    a, b = _two_citations(db_session)
    request = citations.PanelSummaryIn(question="Why 18 weekly sets?", citation_ids=[a.id, b.id])

    assert citations.get_panel_summary(request, db_session, user).summary is None
    assert mock_write.call_count == 2  # one retry
    assert db_session.query(models.SharedAnswer).filter(models.SharedAnswer.field == "citations_summary").count() == 0
    citations.get_panel_summary(request, db_session, user)
    assert mock_write.call_count == 2  # a failed panel isn't paid for again


def test_panel_summary_needs_known_citations_and_bounded_input(db_session, owner_and_prescription):
    import pydantic
    import pytest
    from fastapi import HTTPException

    user, _ = owner_and_prescription
    a = _citation(db_session)
    with pytest.raises(HTTPException) as missing:
        citations.get_panel_summary(citations.PanelSummaryIn(question="Why?", citation_ids=[a.id, 10**9]),
                                    db_session, user)
    assert missing.value.status_code == 404
    for bad in ({"question": "x" * 301, "citation_ids": [1]}, {"question": "Why?", "citation_ids": []},
                {"question": "Why?", "citation_ids": list(range(21))}):
        with pytest.raises(pydantic.ValidationError):
            citations.PanelSummaryIn(**bad)


@patch("app.rag.citation_summaries.verify_citation", side_effect=["contextual_support", "primary_support"])
@patch("app.rag.citation_summaries.write_summary", side_effect=["Loose summary.", "Faithful summary."])
def test_only_a_directly_stated_summary_passes(_write, _verify):
    assert checked_summary("Paper", "excerpt") == "Faithful summary."
