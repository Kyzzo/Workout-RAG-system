from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.generation import (
    generate_frequency_endpoint,
    generate_intensity,
    generate_progression_endpoint,
    generate_volume,
)


def _fake_result(sets, chunk_ids, grounding):
    return SimpleNamespace(sets=sets, chunk_ids=chunk_ids, grounding=grounding)


def _fake_intensity_result(load, chunk_ids, grounding):
    return SimpleNamespace(load=load, chunk_ids=chunk_ids, grounding=grounding)


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


# --- intensity/load: proves the shared orchestration generalizes to a
# second category correctly (a different field name, a non-int type, and
# use_mechanical_check=False actually being respected) rather than
# re-testing retry/messaging branches already covered above for volume,
# since that logic is identical shared code for both categories.

@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_intensity_load")
def test_generate_intensity_success(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_generate.return_value = (
        _fake_intensity_result("70% 1RM", ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    result = generate_intensity(prescription_id=prescription.id, db=db_session, current_user=user)

    assert result.load == "70% 1RM"
    assert result.grounding_note is None
    mock_generate.assert_called_once()

    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verification_status == "primary_support"


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_intensity_load")
def test_intensity_never_uses_mechanical_check(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_generate.return_value = (
        _fake_intensity_result("70% 1RM", ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    generate_intensity(prescription_id=prescription.id, db=db_session, current_user=user)

    # verify_citation must have been called with use_mechanical_check=False
    # for every call - this is what actually proves the parameterization
    # flows through correctly, not just that the endpoint happens to work.
    for call in mock_verify.call_args_list:
        assert call.kwargs.get("use_mechanical_check") is False


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_intensity_load")
def test_intensity_ownership_enforced(mock_generate, mock_verify, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mock_generate.return_value = (_fake_intensity_result("70% 1RM", [], "general_knowledge"), [])

    with pytest.raises(HTTPException) as exc_info:
        generate_intensity(prescription_id=prescription.id, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    mock_generate.assert_not_called()


# --- progression: goal-gated (strength only), plus the mechanical
# linear-application formula, which is pure deterministic logic tested
# directly - no LLM call involved once the scheme itself is known.

def _fake_scheme_result(scheme, chunk_ids, grounding):
    return SimpleNamespace(scheme=scheme, chunk_ids=chunk_ids, grounding=grounding)


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_progression_scheme")
def test_progression_rejects_non_strength_goal(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription  # hypertrophy-goal fixture
    mesocycle = prescription.exercise_slot.day_template.mesocycle

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with pytest.raises(HTTPException) as exc_info:
        generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert exc_info.value.status_code == 400
    mock_generate.assert_not_called()  # rejected before ever reaching generation


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_progression_scheme")
def test_progression_linear_applies_mechanically(mock_generate, mock_verify, db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    mock_generate.return_value = (
        _fake_scheme_result("linear", ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    result = generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.scheme.scheme == "linear"
    loads_by_week = {wp.week_number: wp.load for wp in result.updated_prescriptions}
    assert loads_by_week == {2: "72.5% 1RM", 3: "75% 1RM", 4: "45% 1RM"}  # +2.5%/week, deload = 60% of peak

    # week 1's real baseline must be untouched
    db_session.refresh(mesocycle)
    week1 = next(
        wp for day in mesocycle.day_templates for s in day.exercise_slots for wp in s.weekly_prescriptions
        if wp.week_number == 1
    )
    assert week1.load == "70% 1RM"


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_progression_scheme")
def test_progression_undulating_leaves_prescriptions_untouched(mock_generate, mock_verify, db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    mock_generate.return_value = (
        _fake_scheme_result("undulating", ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    result = generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.scheme.scheme == "undulating"
    assert result.updated_prescriptions == []  # mechanical application only exists for linear


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_progression_scheme")
def test_progression_ownership_enforced(mock_generate, mock_verify, db_session, strength_owner_and_prescription, other_user):
    _, mesocycle = strength_owner_and_prescription
    mock_generate.return_value = (_fake_scheme_result("linear", [], "general_knowledge"), [])

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with pytest.raises(HTTPException) as exc_info:
        generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    mock_generate.assert_not_called()


# --- frequency: a genuinely different persistence shape (Mesocycle-scoped,
# not WeeklyPrescription-scoped) plus the day-reconciliation logic, which
# is new behavior none of the above categories have.

def _fake_frequency_result(frequency, chunk_ids, grounding):
    return SimpleNamespace(frequency=frequency, chunk_ids=chunk_ids, grounding=grounding)


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_frequency")
def test_frequency_adds_missing_days(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mesocycle = prescription.exercise_slot.day_template.mesocycle  # start_week=1, end_week=6; one existing chest day
    mock_generate.return_value = (
        _fake_frequency_result(3, ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    request = schemas.GenerateFrequencyRequest(muscle_group="chest")
    result = generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.frequency.frequency == 3
    assert len(result.days_added) == 2  # 1 existing chest day -> 3 total needs 2 more

    for day in result.days_added:
        assert day.name == "Push"  # cloned from the source day
        assert [s.exercise_name for s in day.exercise_slots] == ["Barbell Bench Press"]
        weeks = sorted(wp.week_number for s in day.exercise_slots for wp in s.weekly_prescriptions)
        assert weeks == [1, 2, 3, 4, 5, 6]  # full mesocycle range, not partial
        for s in day.exercise_slots:
            for wp in s.weekly_prescriptions:
                assert (wp.sets, wp.reps, wp.load) == (0, "", "")  # honest placeholder, not copied values

    # the ORIGINAL day's real prescription must be untouched by reconciliation
    db_session.refresh(prescription)
    assert prescription.sets == 0 and prescription.reps == "8-10"  # fixture's original seeded value


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_frequency")
def test_frequency_no_gap_adds_nothing(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    mock_generate.return_value = (
        _fake_frequency_result(1, ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    request = schemas.GenerateFrequencyRequest(muscle_group="chest")
    result = generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.days_added == []  # target already met by the one existing day


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_frequency")
def test_frequency_no_source_day_raises(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    mock_generate.return_value = (
        _fake_frequency_result(2, ["chunk-1"], "fully_grounded"),
        _fake_chunks("chunk-1"),
    )
    mock_verify.return_value = "primary_support"

    # no existing day trains "hamstrings" - nothing to clone from
    request = schemas.GenerateFrequencyRequest(muscle_group="hamstrings")
    with pytest.raises(HTTPException) as exc_info:
        generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert exc_info.value.status_code == 400


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_frequency")
def test_frequency_ownership_enforced(mock_generate, mock_verify, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    mock_generate.return_value = (_fake_frequency_result(2, [], "general_knowledge"), [])

    request = schemas.GenerateFrequencyRequest(muscle_group="chest")
    with pytest.raises(HTTPException) as exc_info:
        generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    mock_generate.assert_not_called()
