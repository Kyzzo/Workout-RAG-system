# Per-field citation tagging: sets and load are generated, cited and
# verified independently, so each keeps its own citations and grounding
# note - generating one must never wipe or overwrite the other's.
from types import SimpleNamespace
from unittest.mock import patch

from app import models, schemas
from app.routers.chat import send_chat_message
from app.routers.generation import (
    generate_frequency_endpoint,
    generate_intensity,
    generate_progression_endpoint,
    generate_volume,
)
from app.routers.programs import get_program


def _chunks(*ids):
    return [{"id": cid, "text": f"excerpt for {cid}", "source": f"paper-{cid}"} for cid in ids]


def _result(**fields):
    return SimpleNamespace(**fields)


def _citation_fields(db_session, prescription_id):
    rows = db_session.query(models.PrescriptionCitation).filter_by(prescription_id=prescription_id).all()
    return sorted(row.field for row in rows)


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_intensity_load")
@patch("app.routers.generation.generate_volume_sets")
def test_generating_load_keeps_sets_citations_and_note(mock_sets, mock_load, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_sets.return_value = (_result(sets=12, chunk_ids=["vol-1"], grounding="fully_grounded"), _chunks("vol-1"))
    mock_load.return_value = (_result(load="70% 1RM", chunk_ids=[], grounding="general_knowledge"), [])
    mock_verify.return_value = "primary_support"

    generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)
    result = generate_intensity(prescription_id=prescription.id, db=db_session, current_user=user)

    # Before per-field tagging, this second call deleted the sets citation
    # and its caveat replaced the (empty) sets note.
    assert _citation_fields(db_session, prescription.id) == ["sets"]
    assert [c.citation.title for c in result.sets_citations] == ["paper-vol-1"]
    assert result.sets_grounding_note is None
    assert result.load_grounding_note is not None  # load's own honest caveat


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_regenerating_sets_replaces_only_sets_citations(mock_sets, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    load_citation = models.Citation(title="load-paper", snippet="s", qdrant_point_id="load-1")
    db_session.add(load_citation)
    db_session.flush()
    db_session.add(models.PrescriptionCitation(
        prescription_id=prescription.id, citation_id=load_citation.id, field="load", verification_status="primary_support",
    ))
    db_session.flush()
    mock_sets.return_value = (_result(sets=10, chunk_ids=["vol-1"], grounding="fully_grounded"), _chunks("vol-1"))
    mock_verify.return_value = "primary_support"

    generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)
    generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    assert _citation_fields(db_session, prescription.id) == ["load", "sets"]  # one each, nothing stacked


def test_program_view_shows_only_supported_citations_per_field(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    for i, (field, status) in enumerate([("sets", "primary_support"), ("load", "contextual_support"), ("load", "contradicted")]):
        citation = models.Citation(title=f"paper-{i}", snippet="s", qdrant_point_id=f"chunk-{i}")
        db_session.add(citation)
        db_session.flush()
        db_session.add(models.PrescriptionCitation(
            prescription_id=prescription.id, citation_id=citation.id, field=field, verification_status=status,
        ))
    db_session.flush()
    db_session.expire_all()

    program = schemas.ProgramOut.model_validate(
        get_program(program_id=prescription.exercise_slot.day_template.mesocycle.program_id, db=db_session, current_user=user)
    )

    wp = program.mesocycles[0].day_templates[0].exercise_slots[0].weekly_prescriptions[0]
    assert [c.citation.title for c in wp.sets_citations] == ["paper-0"]
    # the contradicted load citation is kept in the database but never shown
    assert [(c.citation.title, c.verification_status) for c in wp.load_citations] == [("paper-1", "contextual_support")]


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_frequency")
def test_regenerating_frequency_replaces_previous_record(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    mock_generate.return_value = (_result(frequency=1, chunk_ids=["freq-1"], grounding="fully_grounded"), _chunks("freq-1"))
    mock_verify.return_value = "primary_support"
    request = schemas.GenerateFrequencyRequest(muscle_group="chest")

    generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)
    generate_frequency_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    records = db_session.query(models.MuscleGroupFrequency).filter_by(mesocycle_id=mesocycle.id, muscle_group="chest").all()
    assert len(records) == 1
    # old record's citations went with it; scoped to this mesocycle since
    # tests run against the real dev database inside a rolled-back transaction
    citations = (
        db_session.query(models.FrequencyCitation)
        .join(models.MuscleGroupFrequency)
        .filter(models.MuscleGroupFrequency.mesocycle_id == mesocycle.id)
        .count()
    )
    assert citations == 1


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_progression_scheme")
def test_regenerating_progression_replaces_previous_record(mock_generate, mock_verify, db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    mock_generate.return_value = (_result(scheme="undulating", chunk_ids=["prog-1"], grounding="fully_grounded"), _chunks("prog-1"))
    mock_verify.return_value = "primary_support"
    request = schemas.GenerateProgressionRequest(muscle_group="chest")

    generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)
    generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert db_session.query(models.ProgressionScheme).filter_by(mesocycle_id=mesocycle.id).count() == 1
    citations = (
        db_session.query(models.ProgressionSchemeCitation)
        .join(models.ProgressionScheme)
        .filter(models.ProgressionScheme.mesocycle_id == mesocycle.id)
        .count()
    )
    assert citations == 1


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_progression_scheme")
def test_linear_progression_drops_stale_load_citations(mock_generate, mock_verify, db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    week2 = next(
        wp for day in mesocycle.day_templates for s in day.exercise_slots for wp in s.weekly_prescriptions
        if wp.week_number == 2
    )
    # Week 2 already had a generated, cited load (and a cited sets value)
    # before progression overwrites its load mechanically.
    for field in ("sets", "load"):
        citation = models.Citation(title=f"{field}-paper", snippet="s", qdrant_point_id=f"{field}-1")
        db_session.add(citation)
        db_session.flush()
        db_session.add(models.PrescriptionCitation(
            prescription_id=week2.id, citation_id=citation.id, field=field, verification_status="primary_support",
        ))
    db_session.flush()
    mock_generate.return_value = (_result(scheme="linear", chunk_ids=["prog-1"], grounding="fully_grounded"), _chunks("prog-1"))
    mock_verify.return_value = "primary_support"

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    db_session.refresh(week2)
    assert week2.load == "72.5% 1RM"
    # The old load citations never backed 72.5% - they're gone, the note
    # says where the number came from, and the sets citation is untouched.
    assert _citation_fields(db_session, week2.id) == ["sets"]
    assert "linear progression" in week2.load_grounding_note


@patch("app.routers.chat.route_chat_message")
@patch("app.routers.chat._generate_and_persist")
def test_chat_adjust_returns_the_target_fields_note(mock_persist, mock_route, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.sets_grounding_note = "sets caveat"
    prescription.load_grounding_note = "load caveat"
    mock_persist.return_value = prescription
    mock_route.return_value = SimpleNamespace(
        tool="adjust_prescription", field_id=prescription.id, target_field="load",
        requested_change=None, question=None, topic=None,
    )

    result = send_chat_message(
        request=schemas.ChatMessageRequest(message="update my load"), db=db_session, current_user=user
    )

    assert result.grounding_note == "load caveat"
