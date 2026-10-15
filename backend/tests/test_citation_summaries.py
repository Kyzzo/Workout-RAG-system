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


@patch("app.rag.citation_summaries.verify_citation", side_effect=["contextual_support", "primary_support"])
@patch("app.rag.citation_summaries.write_summary", side_effect=["Loose summary.", "Faithful summary."])
def test_only_a_directly_stated_summary_passes(_write, _verify):
    assert checked_summary("Paper", "excerpt") == "Faithful summary."
