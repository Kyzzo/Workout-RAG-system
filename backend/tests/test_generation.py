from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models
from app.routers.generation import generate_volume


def _fake_result(sets, chunk_ids, grounding):
    return SimpleNamespace(sets=sets, chunk_ids=chunk_ids, grounding=grounding)


def _fake_chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_generate_volume_success(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_generate.return_value = (_fake_result(12, ["chunk-1"], "fully_grounded"), _fake_chunks("chunk-1"))
    mock_verify.return_value = "primary_support"

    result = generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    assert result.sets == 12
    assert result.grounding_note is None
    mock_generate.assert_called_once()  # no retry needed - it was supported on the first try

    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verification_status == "primary_support"


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_ownership_enforced(mock_generate, mock_verify, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mock_generate.return_value = (_fake_result(12, [], "general_knowledge"), [])

    with pytest.raises(HTTPException) as exc_info:
        generate_volume(prescription_id=prescription.id, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    mock_generate.assert_not_called()  # rejected before ever reaching generation


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_general_knowledge_skips_retry(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    # An honest "nothing supports this" self-report - no citations, no retry,
    # since re-asking the same question won't change the model's honesty.
    mock_generate.return_value = (_fake_result(10, [], "general_knowledge"), [])

    result = generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    assert result.sets == 10
    assert result.grounding_note == (
        "This is a general estimate based on established training principles, "
        "not a specific study."
    )
    mock_generate.assert_called_once()  # confirms no retry fired for this case

    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert len(rows) == 0


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_retry_recovers(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_generate.side_effect = [
        (_fake_result(12, ["chunk-1"], "fully_grounded"), _fake_chunks("chunk-1")),
        (_fake_result(14, ["chunk-2"], "fully_grounded"), _fake_chunks("chunk-2")),
    ]
    mock_verify.side_effect = ["contradicted", "primary_support"]

    result = generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    assert result.sets == 14  # the RETRY's value, not the first (discarded) attempt's
    assert result.grounding_note is None
    assert mock_generate.call_count == 2

    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert len(rows) == 1  # only the retry's citation persisted, not the discarded first attempt's
    assert rows[0].verification_status == "primary_support"


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_retry_exhausted_shows_value_with_caveat(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_generate.side_effect = [
        (_fake_result(12, ["chunk-1"], "fully_grounded"), _fake_chunks("chunk-1")),
        (_fake_result(13, ["chunk-2"], "blended"), _fake_chunks("chunk-2")),
    ]
    mock_verify.side_effect = ["contradicted", "contradicted"]

    result = generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    # The value is still shown - never withheld - even though grounding failed.
    assert result.sets == 13
    assert result.grounding_note == "This value could not be substantiated by the current research corpus."
    assert mock_generate.call_count == 2  # exactly one retry, never a loop

    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verification_status == "contradicted"  # retained for QA, just not displayed as valid


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_regenerating_replaces_stale_citations(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription

    mock_generate.return_value = (_fake_result(12, ["chunk-1"], "fully_grounded"), _fake_chunks("chunk-1"))
    mock_verify.return_value = "primary_support"
    generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    mock_generate.return_value = (_fake_result(15, ["chunk-2"], "fully_grounded"), _fake_chunks("chunk-2"))
    mock_verify.return_value = "primary_support"
    generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert len(rows) == 1  # the first call's citation was replaced, not accumulated alongside
