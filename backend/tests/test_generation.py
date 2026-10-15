from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.generation import (
    _sibling_volume_summary,
    generate_frequency_endpoint,
    generate_intensity,
    generate_progression_endpoint,
    generate_volume,
)


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
    assert result.sets_grounding_note is None
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
    assert result.sets_grounding_note == (
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
    assert result.sets_grounding_note is None
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
    assert result.sets_grounding_note == "This value could not be substantiated by the current research corpus."
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
# its own verification calls) rather than
# re-testing retry/messaging branches already covered above for volume,
# since that logic is identical shared code for both categories.

@patch("app.routers.generation.generate_intensity_load")
def test_gen_load_derives_the_load_from_the_weeks_reps_and_rir(mock_generate, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.reps, prescription.rir = "3-5", "1-2 RIR"
    prescription.exercise_slot.exercise_name = "Barbell Back Squat"
    with patch("app.routers.generation.justify_rule", return_value=_fake_rule(db_session)):
        result = generate_intensity(prescription_id=prescription.id, db=db_session, current_user=user)

    assert result.load == "86.5% 1RM"  # 5 reps + 1.5 RIR = 6.5 reps to failure
    mock_generate.assert_not_called()  # no separate generation to contradict reps and RIR
    rows = (
        db_session.query(models.PrescriptionCitation)
        .filter(models.PrescriptionCitation.prescription_id == prescription.id)
        .all()
    )
    assert [(r.field, r.verification_status) for r in rows] == [("load", "primary_support")]


# --- sibling-exercise volume context: the cross-exercise volume-coherence
# fix (datamodel.txt) - generation for one exercise now gets told what's
# already prescribed for OTHER exercises sharing its muscle_group this
# week, so it doesn't independently re-allocate the full research range.

def _add_sibling_slot(db_session, day_template, muscle_group, exercise_name, week_number, sets, load=""):
    slot = models.ExerciseSlot(
        day_template_id=day_template.id, exercise_name=exercise_name, muscle_group=muscle_group, order=2,
    )
    db_session.add(slot)
    db_session.flush()
    db_session.add(models.WeeklyPrescription(
        exercise_slot_id=slot.id, week_number=week_number, sets=sets, reps="8-10", load=load,
    ))
    db_session.flush()
    return slot


def test_sibling_volume_summary_includes_same_muscle_group_same_week(db_session, owner_and_prescription):
    _, prescription = owner_and_prescription
    day_template = prescription.exercise_slot.day_template
    _add_sibling_slot(db_session, day_template, "chest", "Incline Dumbbell Press", week_number=1, sets=3)

    summary = _sibling_volume_summary(prescription, db_session)

    assert summary == "- Incline Dumbbell Press: 3 sets"


def test_sibling_volume_summary_excludes_other_muscle_groups_and_weeks(db_session, owner_and_prescription):
    _, prescription = owner_and_prescription  # chest, week 1
    day_template = prescription.exercise_slot.day_template
    _add_sibling_slot(db_session, day_template, "back", "Barbell Row", week_number=1, sets=4)  # different muscle group
    _add_sibling_slot(db_session, day_template, "chest", "Incline Dumbbell Press", week_number=2, sets=3)  # different week

    summary = _sibling_volume_summary(prescription, db_session)

    assert summary is None


def test_sibling_volume_summary_counts_secondary_work_at_half(db_session, owner_and_prescription):
    _, prescription = owner_and_prescription  # chest, week 1
    day_template = prescription.exercise_slot.day_template
    dips = _add_sibling_slot(db_session, day_template, "triceps", "Dips", week_number=1, sets=4)
    dips.secondary_muscle_groups = ["chest", "front delts"]
    _add_sibling_slot(db_session, day_template, "chest", "Cable Fly", week_number=1, sets=3)
    db_session.flush()

    summary = _sibling_volume_summary(prescription, db_session)

    assert sorted(summary.splitlines()) == [
        "- Cable Fly: 3 sets",
        "- Dips: 4 sets (trains it secondarily, counts as 2)",
    ]


def test_sibling_volume_summary_skips_ungenerated_siblings(db_session, owner_and_prescription):
    _, prescription = owner_and_prescription
    day_template = prescription.exercise_slot.day_template
    # sets=0, load="" is the honest "not generated yet" placeholder from
    # day-cloning/manual creation, not a real allocation - reporting "0
    # sets" would misleadingly suggest that budget is confirmed free.
    _add_sibling_slot(db_session, day_template, "chest", "Incline Dumbbell Press", week_number=1, sets=0, load="")

    summary = _sibling_volume_summary(prescription, db_session)

    assert summary is None


@patch("app.routers.generation.verify_citation")
@patch("app.routers.generation.generate_volume_sets")
def test_generate_volume_passes_sibling_context(mock_generate, mock_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    day_template = prescription.exercise_slot.day_template
    _add_sibling_slot(db_session, day_template, "chest", "Incline Dumbbell Press", week_number=1, sets=3)
    mock_generate.return_value = (_fake_result(8, [], "general_knowledge"), [])
    mock_verify.return_value = "unresolved"

    generate_volume(prescription_id=prescription.id, db=db_session, current_user=user)

    _, kwargs = mock_generate.call_args
    assert kwargs["sibling_context"] == "- Incline Dumbbell Press: 3 sets"


@patch("app.rag.verification.judge_citation")
def test_a_covering_range_never_approves_a_citation_without_the_judge(mock_judge):
    # Regression: 18 weekly quad sets for hypertrophy was approved from Aube
    # 2022's '12-24 sets' range by a range shortcut, though the judge
    # rejected it (Aube's 18 is a strength finding). Every citation is judged.
    from app.rag.verification import verify_citation
    mock_judge.return_value = SimpleNamespace(outcome="contradicted", reasoning="strength finding")

    status = verify_citation(
        "weekly quad sets for hypertrophy", 18,
        "12-24 weekly sets produced similar muscle mass; ~18 weekly sets may optimize squat 1RM",
    )

    assert status == "contradicted"
    mock_judge.assert_called_once()


@patch("app.routers.generation.justify_rule")
def test_intensity_ownership_enforced(mock_rule, db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription

    with pytest.raises(HTTPException) as exc_info:
        generate_intensity(prescription_id=prescription.id, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    mock_rule.assert_not_called()


# --- progression: goal-gated (strength only). The scheme comes from the
# program's training status via a cited rule (no LLM call here), and the
# week-by-week write-back is deterministic logic tested directly.

def _fake_rule(db_session, note=None):
    citation = models.Citation(title="periodization-paper", snippet="s", qdrant_point_id="prog-1")
    db_session.add(citation)
    db_session.flush()
    return SimpleNamespace(
        grounding_note=note,
        rule_citations=[SimpleNamespace(citation_id=citation.id, verification_status="primary_support")],
    )


def _loads_by_week(result):
    return {wp.week_number: wp.load for wp in result.updated_prescriptions}


def _weeks(result):
    return {wp.week_number: (wp.load, wp.reps, wp.rir) for wp in result.updated_prescriptions}


def _progress(db_session, user, mesocycle, trained=False, include_deload=False):
    # The fixture's week 1: 5 reps at 70% 1RM on the bench press; RIR 1-2.
    mesocycle.program.trained = trained
    mesocycle.program.include_deload = include_deload
    week1 = next(
        wp for day in mesocycle.day_templates for s in day.exercise_slots for wp in s.weekly_prescriptions
        if wp.week_number == 1
    )
    week1.rir = "1-2 RIR"
    db_session.flush()
    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with patch("app.routers.generation.justify_rule", return_value=_fake_rule(db_session)) as mock_rule:
        result = generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)
    expected = ["periodization_by_training_status", "reps_at_percent_1rm"]
    if trained:
        expected.append("daily_undulating_protocol")
    expected.append("linear_periodization_protocol")
    assert [c.args[1] for c in mock_rule.call_args_list] == expected
    return result


def _bench_days(db_session, mesocycle, days):
    # The block's chest work for a trained lifter: Barbell Bench Press on each
    # of `days` days (compound), plus a Cable Fly (isolation) on the first;
    # week 1 as generated: 1-5 reps at 1-2 RIR, a derived 86.5% load.
    mesocycle.program.trained = True
    for day in list(mesocycle.day_templates):
        db_session.delete(day)
    db_session.flush()
    slots = []
    for order in range(1, days + 1):
        day = models.DayTemplate(mesocycle_id=mesocycle.id, name=f"Day {order}", order=order)
        db_session.add(day)
        db_session.flush()
        names = [("Barbell Bench Press", True)] + ([("Cable Fly", False)] if order == 1 else [])
        for i, (name, compound) in enumerate(names, start=1):
            slot = models.ExerciseSlot(
                day_template_id=day.id, exercise_name=name, muscle_group="chest", is_compound=compound, order=i,
            )
            slot.weekly_prescriptions = [
                models.WeeklyPrescription(week_number=w, sets=3, reps="1-5", load="86.5% 1RM", rir="1-2 RIR")
                for w in range(1, 5)
            ]
            db_session.add(slot)
            slots.append(slot)
    db_session.flush()
    db_session.expire(mesocycle)
    return slots


def _undulate(db_session, user, mesocycle, include_deload=False):
    mesocycle.program.include_deload = include_deload
    db_session.flush()
    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with patch("app.routers.generation.justify_rule", return_value=_fake_rule(db_session)) as mock_rule:
        result = generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)
    assert [c.args[1] for c in mock_rule.call_args_list] == [
        "periodization_by_training_status", "reps_at_percent_1rm", "daily_undulating_protocol",
        "linear_periodization_protocol",
    ]
    return result


def _by_day(result, slots):
    # (reps, load, rir) per bench slot (day order), each as {week: ...}
    by_slot = {}
    for wp in result.updated_prescriptions:
        by_slot.setdefault(wp.exercise_slot_id, {})[wp.week_number] = (wp.reps, wp.load, wp.rir)
    return [by_slot.get(s.id) for s in slots if s.exercise_name == "Barbell Bench Press"]


@patch("app.routers.generation.justify_rule")
def test_progression_rejects_non_strength_goal(mock_rule, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription  # hypertrophy-goal fixture
    mesocycle = prescription.exercise_slot.day_template.mesocycle

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with pytest.raises(HTTPException) as exc_info:
        generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert exc_info.value.status_code == 400
    mock_rule.assert_not_called()


def test_untrained_lifter_gets_linear_progression(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription

    result = _progress(db_session, user, mesocycle, trained=False)

    assert result.scheme.scheme == "linear"
    assert [c.verification_status for c in result.scheme.supporting_citations] == ["primary_support"]
    # Rhea's and Buford's linear arms: phases of 8, 6 and 4 reps - 4 weeks
    # split 2/1/1 - each load from its reps + 1.5 RIR on the bench press table
    assert _weeks(result) == {
        1: ("78.5% 1RM", "8", "1-2 RIR"), 2: ("78.5% 1RM", "8", "1-2 RIR"),
        3: ("82.5% 1RM", "6", "1-2 RIR"), 4: ("86.5% 1RM", "4", "1-2 RIR"),
    }
    week3 = next(wp for wp in result.updated_prescriptions if wp.week_number == 3)
    assert "Phase 2 of 3" in week3.reps_grounding_note and "as evenly as possible" in week3.reps_grounding_note
    assert [c.verification_status for c in week3.reps_citations] == ["primary_support"]  # the rule's


def test_trained_lifter_gets_rheas_daily_undulation(db_session, strength_owner_and_prescription):
    # Rhea et al. 2002: each week's three sessions at 8, 6 and 4 reps,
    # heaviest last. Each day's load comes from its reps + the RIR on the
    # bench press table (9.5 / 7.5 / 5.5 reps to failure); every week the same.
    user, mesocycle = strength_owner_and_prescription
    slots = _bench_days(db_session, mesocycle, 3)

    result = _undulate(db_session, user, mesocycle)

    assert result.scheme.scheme == "undulating"
    days = _by_day(result, slots)
    for day, (reps, load) in zip(days, [("8", "78.5% 1RM"), ("6", "82.5% 1RM"), ("4", "86.5% 1RM")]):
        assert day == {w: (reps, load, "1-2 RIR") for w in range(1, 5)}
    fly = next(s for s in slots if s.exercise_name == "Cable Fly")
    assert all(wp.reps == "1-5" for wp in fly.weekly_prescriptions)  # accessories don't undulate
    day1_week1 = next(wp for wp in result.updated_prescriptions if wp.exercise_slot_id == slots[0].id)
    assert "Rhea et al. 2002" in day1_week1.reps_grounding_note
    assert "starting weight" in day1_week1.load_grounding_note


def test_two_sessions_use_the_ends_of_the_rotation(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    slots = _bench_days(db_session, mesocycle, 2)

    result = _undulate(db_session, user, mesocycle)

    assert [day[1][0] for day in _by_day(result, slots)] == ["8", "4"]
    note = next(wp for wp in result.updated_prescriptions if wp.exercise_slot_id == slots[0].id).reps_grounding_note
    assert "adapted" in note and "convention" in note


def test_one_session_a_week_falls_back_to_linear(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    _bench_days(db_session, mesocycle, 1)

    result = _undulate(db_session, user, mesocycle)

    assert result.scheme.scheme == "linear"
    assert "at least two days a week" in result.scheme.grounding_note


def test_undulating_deload_lightens_each_day(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    slots = _bench_days(db_session, mesocycle, 3)

    result = _undulate(db_session, user, mesocycle, include_deload=True)

    days = _by_day(result, slots)
    # week 4: 60% of each day's load, same reps, RIR recalculated
    assert [day[4][:2] for day in days] == [("8", "47% 1RM"), ("6", "49.5% 1RM"), ("4", "52% 1RM")]
    assert days[2][4][2] == "~21 RIR"  # 52%: ~25.5 reps to failure on the bench press, minus 4 reps
    assert days[0][3] == ("8", "78.5% 1RM", "1-2 RIR")  # earlier weeks unchanged


def test_deload_week_is_only_added_when_chosen(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription

    result = _progress(db_session, user, mesocycle, include_deload=True)

    # three progressive weeks, one per phase; the deload keeps the last
    # phase's reps at 60% of the peak load, so its RIR is what changes
    assert _weeks(result) == {
        1: ("78.5% 1RM", "8", "1-2 RIR"), 2: ("82.5% 1RM", "6", "1-2 RIR"),
        3: ("86.5% 1RM", "4", "1-2 RIR"), 4: ("52% 1RM", "4", "~21 RIR"),
    }
    week4 = next(wp for wp in result.updated_prescriptions if wp.week_number == 4)
    assert "deload" in week4.load_grounding_note
    assert "Nuzzo et al. 2024" in week4.rir_grounding_note


def test_progression_shows_the_rule_note_when_unsupported(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with patch("app.routers.generation.justify_rule", return_value=_fake_rule(db_session, note="no support")):
        result = generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=user)

    assert result.scheme.grounding_note == "no support"


@patch("app.routers.generation.justify_rule")
def test_progression_ownership_enforced(mock_rule, db_session, strength_owner_and_prescription, other_user):
    _, mesocycle = strength_owner_and_prescription

    request = schemas.GenerateProgressionRequest(muscle_group="chest")
    with pytest.raises(HTTPException) as exc_info:
        generate_progression_endpoint(mesocycle_id=mesocycle.id, request=request, db=db_session, current_user=other_user)

    assert exc_info.value.status_code == 404
    mock_rule.assert_not_called()


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


def test_a_muscle_with_only_accessories_keeps_its_prescription(db_session, strength_owner_and_prescription):
    # The smoke test's side delts: only lateral raises, which linear
    # progression had pushed to 3 reps at 89.5% 1RM. The trials periodized
    # their main lifts only.
    user, mesocycle = strength_owner_and_prescription
    slot = mesocycle.day_templates[0].exercise_slots[0]
    slot.exercise_name, slot.is_compound = "Dumbbell Lateral Raise", False

    result = _progress(db_session, user, mesocycle)

    assert result.scheme.scheme == "constant"
    assert "no compound lift" in result.scheme.grounding_note
    assert result.updated_prescriptions == []


def test_undulating_deload_also_lightens_accessories(db_session, strength_owner_and_prescription):
    user, mesocycle = strength_owner_and_prescription
    slots = _bench_days(db_session, mesocycle, 3)

    result = _undulate(db_session, user, mesocycle, include_deload=True)

    fly = next(s for s in slots if s.exercise_name == "Cable Fly")
    fly_weeks = {wp.week_number: wp for wp in result.updated_prescriptions if wp.exercise_slot_id == fly.id}
    assert list(fly_weeks) == [4]  # only the deload week changes for an accessory
    assert fly_weeks[4].load == "52% 1RM"  # 60% of its 86.5%
