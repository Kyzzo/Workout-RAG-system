# Chat "adjust" now honors what was asked: an exact value is applied as a
# user override (cited only by what genuinely supports it), a direction
# moves the value that way or keeps it and explains why.
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.rag.generate import build_intensity_query, build_volume_query
from app.routers.chat import send_chat_message


def _route(prescription, target_field, adjustment_kind, requested_value=None):
    return SimpleNamespace(
        tool="adjust_prescription", field_id=prescription.id, target_field=target_field,
        adjustment_kind=adjustment_kind, requested_value=requested_value,
        requested_change="the user's request", question=None, topic=None,
    )


def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


def _send(db_session, user, prescription):
    return send_chat_message(
        request=schemas.ChatMessageRequest(message="change it", field_id=prescription.id),
        db=db_session, current_user=user,
    )


def _patch_field(field, generate_mock):
    # _ADJUST_FIELDS captured the real generate functions at import time,
    # so the mock has to go into the dict itself.
    query_fn, mechanical = (build_volume_query, True) if field == "sets" else (build_intensity_query, False)
    return patch.dict("app.routers.chat._ADJUST_FIELDS", {field: (generate_mock, query_fn, mechanical)})


@patch("app.routers.generation.verify_citation", return_value="contradicted")
@patch("app.routers.chat.route_chat_message")
def test_exact_value_is_applied_with_override_note_when_unsupported(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.sets = 10
    mock_route.return_value = _route(prescription, "sets", "set_value", "4 sets")
    generate = MagicMock(return_value=(SimpleNamespace(sets=4, chunk_ids=[], grounding="general_knowledge"), []))

    with _patch_field("sets", generate):
        result = _send(db_session, user, prescription)

    adjustment = generate.call_args.kwargs["adjustment"]
    assert (adjustment.kind, adjustment.requested_value) == ("set_value", 4)
    assert result.prescription.sets == 4
    assert result.grounding_note == "Set by you - the current research corpus doesn't support this specific value."


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.chat.route_chat_message")
def test_exact_value_supported_by_research_gets_citations_not_a_caveat(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.exercise_slot.day_template.mesocycle.program.goal = "strength"  # load is strength-only
    mock_route.return_value = _route(prescription, "load", "set_value", "75% 1RM")
    generate = MagicMock(return_value=(
        SimpleNamespace(load="75% 1RM", chunk_ids=["int-1"], grounding="fully_grounded"), _chunks("int-1"),
    ))

    with _patch_field("load", generate):
        result = _send(db_session, user, prescription)

    assert result.prescription.load == "75% 1RM"
    assert result.grounding_note is None
    assert [c.citation.title for c in result.prescription.load_citations] == ["paper-int-1"]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.chat.route_chat_message")
def test_increase_moves_the_value_up(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.sets = 2
    mock_route.return_value = _route(prescription, "sets", "increase")
    generate = MagicMock(return_value=(SimpleNamespace(sets=4, chunk_ids=["v-1"], grounding="fully_grounded"), _chunks("v-1")))

    with _patch_field("sets", generate):
        result = _send(db_session, user, prescription)

    adjustment = generate.call_args.kwargs["adjustment"]
    assert (adjustment.kind, adjustment.current_value) == ("increase", 2)
    assert result.prescription.sets == 4
    assert result.answer is None


@pytest.mark.parametrize("kind, returned", [("increase", 3), ("decrease", 4)])
@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.chat.route_chat_message")
def test_direction_not_honored_keeps_value_and_existing_citations(
    mock_route, _verify, kind, returned, db_session, owner_and_prescription,
):
    # increase -> unchanged (the prompt's signal that research doesn't
    # support moving), decrease -> moved the wrong way: both keep 3.
    user, prescription = owner_and_prescription
    prescription.sets = 3
    citation = models.Citation(title="kept-paper", snippet="s", qdrant_point_id="kept-1")
    db_session.add(citation)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=prescription.id, citation_id=citation.id, field="sets", verification_status="primary_support",
    ))
    db_session.flush()
    mock_route.return_value = _route(prescription, "sets", kind)
    generate = MagicMock(return_value=(SimpleNamespace(sets=returned, chunk_ids=[], grounding="general_knowledge"), []))

    with _patch_field("sets", generate):
        result = _send(db_session, user, prescription)

    db_session.expire_all()
    stored = db_session.get(models.WeeklyPrescription, prescription.id)
    assert stored.sets == 3
    assert [c.citation.title for c in stored.sets_citations] == ["kept-paper"]
    assert result.answer.startswith("Kept at 3")


@pytest.mark.parametrize("new_load, expected", [
    ("RPE 8", "RPE 8"),          # different unit: can't call it lower, accepted as a change
    ("75% 1RM", "70% 1RM"),      # same unit, went UP on a decrease: kept
    ("65% 1RM", "65% 1RM"),      # same unit, went down: applied
])
@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.chat.route_chat_message")
def test_load_direction_only_compared_within_one_unit(
    mock_route, _verify, new_load, expected, db_session, owner_and_prescription,
):
    user, prescription = owner_and_prescription  # load starts at "70% 1RM"
    prescription.exercise_slot.day_template.mesocycle.program.goal = "strength"  # load is strength-only
    mock_route.return_value = _route(prescription, "load", "decrease")
    generate = MagicMock(return_value=(SimpleNamespace(load=new_load, chunk_ids=[], grounding="general_knowledge"), []))

    with _patch_field("load", generate):
        result = _send(db_session, user, prescription)

    assert result.prescription.load == expected


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.chat.route_chat_message")
def test_direction_on_ungenerated_value_just_generates(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription  # sets=0: placeholder, nothing to move from
    mock_route.return_value = _route(prescription, "sets", "increase")
    generate = MagicMock(return_value=(SimpleNamespace(sets=12, chunk_ids=[], grounding="general_knowledge"), []))

    with _patch_field("sets", generate):
        result = _send(db_session, user, prescription)

    assert generate.call_args.kwargs["adjustment"] is None
    assert result.prescription.sets == 12


@patch("app.routers.chat.route_chat_message")
def test_exact_value_that_isnt_a_number_is_rejected(mock_route, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_route.return_value = _route(prescription, "sets", "set_value", "a bunch")

    with pytest.raises(HTTPException) as exc_info:
        _send(db_session, user, prescription)

    assert exc_info.value.status_code == 400


@patch("app.routers.chat.route_chat_message")
def test_increase_at_the_per_exercise_cap_is_refused_without_generating(mock_route, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription  # hypertrophy: cap is 4
    prescription.sets = 4
    mock_route.return_value = _route(prescription, "sets", "increase")
    generate = MagicMock()

    with _patch_field("sets", generate):
        result = _send(db_session, user, prescription)

    generate.assert_not_called()
    assert result.prescription.sets == 4
    assert "most one exercise gets per session (4)" in result.answer


@patch("app.routers.generation.verify_citation", return_value="contradicted")
@patch("app.routers.chat.route_chat_message")
def test_exact_override_can_exceed_the_cap(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.sets = 4
    mock_route.return_value = _route(prescription, "sets", "set_value", "6")
    generate = MagicMock(return_value=(SimpleNamespace(sets=6, chunk_ids=[], grounding="general_knowledge"), []))

    with _patch_field("sets", generate):
        result = _send(db_session, user, prescription)

    assert result.prescription.sets == 6  # the user's informed override wins


@patch("app.routers.chat.route_chat_message")
def test_hypertrophy_load_request_explains_instead_of_generating(mock_route, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription  # hypertrophy
    mock_route.return_value = _route(prescription, "load", "increase")
    generate = MagicMock()

    with _patch_field("load", generate):
        result = _send(db_session, user, prescription)

    generate.assert_not_called()
    assert "don't prescribe a load" in result.answer


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_rir")
@patch("app.routers.chat.route_chat_message")
def test_closer_to_failure_lowers_rir(mock_route, mock_rir, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.rir = "2-3 RIR"
    mock_route.return_value = _route(prescription, "rir", "decrease")
    mock_rir.return_value = (SimpleNamespace(rir="0-1 RIR", chunk_ids=["r-1"], grounding="fully_grounded"), _chunks("r-1"))

    result = _send(db_session, user, prescription)

    # The exercise name reaches the per-exercise RIR question.
    assert mock_rir.call_args.args[2] == prescription.exercise_slot.exercise_name
    assert result.prescription.rir == "0-1 RIR"
    assert [c.citation.title for c in result.prescription.rir_citations] == ["paper-r-1"]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_rir")
@patch("app.routers.chat.route_chat_message")
def test_rir_moving_the_wrong_way_is_kept(mock_route, mock_rir, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.rir = "1-2 RIR"
    mock_route.return_value = _route(prescription, "rir", "decrease")
    mock_rir.return_value = (SimpleNamespace(rir="2-3 RIR", chunk_ids=[], grounding="general_knowledge"), [])

    result = _send(db_session, user, prescription)

    assert result.prescription.rir == "1-2 RIR"
    assert result.answer.startswith("Kept at 1-2 RIR")


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_reps")
@patch("app.routers.chat.route_chat_message")
def test_hypertrophy_adjustment_applies_to_every_week(mock_route, mock_reps, _verify, db_session, owner_and_prescription):
    # Hypertrophy shows one prescription per exercise, so a change made
    # from it must land on all of that exercise's weeks.
    user, prescription = owner_and_prescription
    for week in (2, 3):
        db_session.add(models.WeeklyPrescription(
            exercise_slot_id=prescription.exercise_slot_id, week_number=week, sets=3, reps="8-10", load="",
        ))
    db_session.flush()
    mock_route.return_value = _route(prescription, "reps", "set_value", "10-12")
    mock_reps.return_value = (SimpleNamespace(reps="10-12", chunk_ids=["rep-1"], grounding="fully_grounded"), _chunks("rep-1"))

    _send(db_session, user, prescription)

    db_session.expire_all()
    weeks = db_session.get(models.ExerciseSlot, prescription.exercise_slot_id).weekly_prescriptions
    assert [wp.reps for wp in weeks] == ["10-12"] * 3
    assert all([c.citation.title for c in wp.reps_citations] == ["paper-rep-1"] for wp in weeks)


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.generation.generate_reps")
@patch("app.routers.chat.route_chat_message")
def test_strength_adjustment_stays_on_its_week(mock_route, mock_reps, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.exercise_slot.day_template.mesocycle.program.goal = "strength"
    db_session.add(models.WeeklyPrescription(
        exercise_slot_id=prescription.exercise_slot_id, week_number=2, sets=3, reps="3-5", load="",
    ))
    db_session.flush()
    mock_route.return_value = _route(prescription, "reps", "set_value", "5-6")
    mock_reps.return_value = (SimpleNamespace(reps="5-6", chunk_ids=[], grounding="general_knowledge"), [])

    _send(db_session, user, prescription)

    db_session.expire_all()
    weeks = db_session.get(models.ExerciseSlot, prescription.exercise_slot_id).weekly_prescriptions
    assert [wp.reps for wp in weeks] == ["5-6", "3-5"]  # strength weeks progress independently
