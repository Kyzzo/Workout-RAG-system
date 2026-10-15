# Exercise swaps: same target muscle, the new exercise gets its own values,
# and the ripple (rotation on other days, other muscles' sets via secondary
# credit) is recalculated and reported.
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.chat import send_chat_message
from app.routers.changes import cancel_change, undo_change
from app.routers.generation import _run_progression, _split_weekly_sets, confirm_swap, swap_exercise


def _rule(db_session):
    citation = models.Citation(title="rule-paper", snippet="s", qdrant_point_id="rule-1")
    db_session.add(citation)
    db_session.flush()
    return SimpleNamespace(
        grounding_note=None,
        rule_citations=[SimpleNamespace(citation_id=citation.id, verification_status="primary_support")],
    )


def _answers(**values):
    # Fake generate_for_movement: the shared reps/RIR answers by field.
    def fake(field, goal, movement, preference="moderate"):
        return (
            SimpleNamespace(**{field: values[field]}, chunk_ids=[f"{field}-1"], grounding="fully_grounded"),
            [{"id": f"{field}-1", "text": f"excerpt {field}", "source": f"paper-{field}"}],
        )
    return fake


def _days(db_session, mesocycle, specs):
    # specs: per day, [(exercise, muscle, is_compound, secondaries, reps)]
    for day in list(mesocycle.day_templates):
        db_session.delete(day)
    db_session.flush()
    slots = []
    for order, picks in enumerate(specs, start=1):
        day = models.DayTemplate(mesocycle_id=mesocycle.id, name=f"Day {order}", order=order)
        db_session.add(day)
        db_session.flush()
        for i, (name, muscle, compound, secondaries, reps) in enumerate(picks, start=1):
            slot = models.ExerciseSlot(
                day_template_id=day.id, exercise_name=name, muscle_group=muscle, is_compound=compound,
                secondary_muscle_groups=secondaries, order=i,
            )
            slot.weekly_prescriptions = [
                models.WeeklyPrescription(week_number=w, sets=3, reps=reps, load="", rir="1-2 RIR")
                for w in range(1, 5)
            ]
            db_session.add(slot)
            slots.append(slot)
    db_session.flush()
    db_session.expire(mesocycle)
    return slots


def _swap(db_session, user, slot, name, classify=None, suggest=None, answers=None, confirm=False):
    # A swap is previewed; with confirm=True it's then applied.
    with patch("app.routers.generation.justify_rule", return_value=_rule(db_session)), \
         patch("app.routers.generation.classify_exercise", return_value=classify) as mock_classify, \
         patch("app.routers.generation.select_additional_exercises", return_value=suggest or []) as mock_suggest, \
         patch("app.routers.generation.generate_for_movement", side_effect=answers or _answers(reps="1-5", rir="1-2 RIR")):
        result = swap_exercise(
            exercise_slot_id=slot.id, request=schemas.SwapExerciseRequest(exercise_name=name),
            db=db_session, current_user=user,
        )
        if confirm:
            result = confirm_swap(db_session, user, result.change_id)
    return result, mock_classify, mock_suggest


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_swapping_a_compound_for_an_accessory_moves_the_rotation_and_says_so(
    _verify, db_session, strength_owner_and_prescription,
):
    # Trained, chest pressed on 3 days (8/6/4). Swapping Day 1's press for
    # flyes leaves 2 compound days, so they become 8 and 4 - Day 2's press
    # goes from 6 reps to 8 - and the flyes get the accessory 8-12.
    user, mesocycle = strength_owner_and_prescription
    mesocycle.program.trained = True
    bench = [("Barbell Bench Press", "chest", True, [], "1-5")]
    slots = _days(db_session, mesocycle, [bench, bench, bench])
    with patch("app.routers.generation.justify_rule", return_value=_rule(db_session)):
        from app.routers.generation import _progression_rules
        _run_progression(db_session, mesocycle, "chest", _progression_rules(db_session, mesocycle.program))
    db_session.flush()

    result, _, _ = _swap(
        db_session, user, slots[0], "Cable Fly", classify=(True, False, []),
        answers=_answers(rir="2-3 RIR"),
    )

    assert (result.old_name, result.new_name) == ("Barbell Bench Press", "Cable Fly")
    assert {wp.reps for wp in result.slot.weekly_prescriptions} == {"8-12"}
    assert "Barbell Bench Press (Day 2): reps 6 -> 8" in result.changes
    assert any(c.startswith("Barbell Bench Press (Day 2): load") for c in result.changes)
    assert not any("Day 3" in c for c in result.changes)  # still the last day: 4 reps
    assert "Cable Fly (Day 1) - the new exercise: reps 8 -> 8-12" in result.changes


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_losing_secondary_credit_resplits_the_other_muscle(_verify, db_session, owner_and_prescription):
    # Bench gives triceps half-credit; swapping it for flyes (no secondaries)
    # means triceps' own exercise has to carry more of its weekly sets.
    user, prescription = owner_and_prescription  # hypertrophy
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    slots = _days(db_session, mesocycle, [[
        ("Barbell Bench Press", "chest", True, ["triceps"], "8-12"),
        ("Triceps Pushdown", "triceps", False, [], "10-15"),
    ]])
    db_session.add(models.MuscleGroupVolume(mesocycle_id=mesocycle.id, muscle_group="triceps", weekly_sets=4))
    db_session.flush()
    db_session.expire(mesocycle)
    # 4 weekly sets - 1.5 credit from 3 sets of bench = 2.5 -> 2 sets of pushdowns
    _split_weekly_sets(mesocycle, "triceps", 4, "hypertrophy")
    pushdown = slots[1]
    assert pushdown.weekly_prescriptions[0].sets == 2

    result, _, _ = _swap(
        db_session, user, slots[0], "Cable Fly", classify=(True, False, []),
        answers=_answers(reps="10-15", rir="1-2 RIR"), confirm=True,
    )

    # no credit left: the pushdowns carry all 4 sets, capped at 3 per exercise
    db_session.refresh(pushdown)
    assert {wp.sets for wp in pushdown.weekly_prescriptions} == {3}
    assert "Triceps Pushdown (Day 1): sets 2 -> 3" in result.changes


def test_a_different_target_muscle_is_refused(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    slot = prescription.exercise_slot
    name_before = slot.exercise_name

    with pytest.raises(HTTPException) as exc_info:
        _swap(db_session, user, slot, "Barbell Row", classify=(False, True, ["lats"]))

    assert exc_info.value.status_code == 400
    assert "doesn't mainly train" in exc_info.value.detail
    assert slot.exercise_name == name_before


def test_a_timed_hold_is_refused_without_classifying(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    with pytest.raises(HTTPException) as exc_info:
        _swap(db_session, user, prescription.exercise_slot, "Plank")
    assert exc_info.value.status_code == 400 and "timed hold" in exc_info.value.detail


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_no_name_gets_a_suggestion_for_the_same_muscle(_verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    slot = prescription.exercise_slot

    result, mock_classify, mock_suggest = _swap(
        db_session, user, slot, None, suggest=[("Dumbbell Bench Press", ["triceps"], True)],
        answers=_answers(reps="8-12", rir="1-2 RIR"),
    )

    mock_classify.assert_not_called()
    assert mock_suggest.call_args.args[1] == slot.muscle_group
    assert result.new_name == "Dumbbell Bench Press"
    assert result.slot.secondary_muscle_groups == ["triceps"]


@patch("app.routers.generation.verify_citation", return_value="primary_support")
@patch("app.routers.chat.route_chat_message")
def test_chat_swap_uses_the_same_engine(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    mock_route.return_value = SimpleNamespace(
        tool="adjust_prescription", field_id=prescription.id, target_field="exercise",
        adjustment_kind="set_value", requested_value="Dumbbell Bench Press",
        requested_change="swap for dumbbell bench", question=None, topic=None,
    )
    with patch("app.routers.generation.justify_rule", return_value=_rule(db_session)), \
         patch("app.routers.generation.classify_exercise", return_value=(True, True, ["triceps"])), \
         patch("app.routers.generation.generate_for_movement", side_effect=_answers(reps="8-12", rir="1-2 RIR")):
        result = send_chat_message(
            request=schemas.ChatMessageRequest(message="swap this for dumbbell bench", field_id=prescription.id),
            db=db_session, current_user=user,
        )

    # a preview: what it would be, nothing applied yet
    assert (result.swap.new_name, result.swap.pending) == ("Dumbbell Bench Press", True)
    assert {wp.reps for wp in result.swap.slot.weekly_prescriptions} == {"8-12"}
    db_session.expire_all()
    assert db_session.get(models.ExerciseSlot, prescription.exercise_slot_id).exercise_name != "Dumbbell Bench Press"


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_a_scheme_change_is_reported(_verify, db_session, strength_owner_and_prescription):
    # Two pressing days undulate (8 and 4); swapping one for flyes leaves one
    # compound day, which can't undulate - chest falls back to linear.
    user, mesocycle = strength_owner_and_prescription
    mesocycle.program.trained = True
    bench = [("Barbell Bench Press", "chest", True, [], "1-5")]
    slots = _days(db_session, mesocycle, [bench, bench])
    with patch("app.routers.generation.justify_rule", return_value=_rule(db_session)):
        from app.routers.generation import _progression_rules
        _run_progression(db_session, mesocycle, "chest", _progression_rules(db_session, mesocycle.program))
    db_session.flush()

    result, _, _ = _swap(
        db_session, user, slots[0], "Cable Fly", classify=(True, False, []), answers=_answers(rir="2-3 RIR"),
    )

    assert result.changes[0].startswith("chest progression: undulating -> linear")
    # Day 2's press was 4 reps every week; linear phases make weeks 1-2 8 reps, week 3 6
    assert any(c.startswith("Barbell Bench Press (Day 2): reps weeks 1-2: 4 -> 8, week 3: 4 -> 6") for c in result.changes)



# --- preview, confirm, cancel and undo

def _state(db_session, mesocycle):
    db_session.expire_all()
    mesocycle = db_session.get(models.Mesocycle, mesocycle.id)
    return {
        (s.exercise_name, wp.week_number): (wp.sets, wp.reps, wp.load, wp.rir)
        for d in mesocycle.day_templates for s in d.exercise_slots for wp in s.weekly_prescriptions
    }, sorted((p.muscle_group, p.scheme) for p in mesocycle.progression_schemes)


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_preview_changes_nothing_and_confirm_applies_exactly_the_preview(
    _verify, db_session, strength_owner_and_prescription,
):
    user, mesocycle = strength_owner_and_prescription
    mesocycle.program.trained = True
    bench = [("Barbell Bench Press", "chest", True, [], "1-5")]
    slots = _days(db_session, mesocycle, [bench, bench, bench])
    with patch("app.routers.generation.justify_rule", return_value=_rule(db_session)):
        from app.routers.generation import _progression_rules
        _run_progression(db_session, mesocycle, "chest", _progression_rules(db_session, mesocycle.program))
    db_session.commit()
    before = _state(db_session, mesocycle)

    preview, _, _ = _swap(db_session, user, slots[0], "Cable Fly", classify=(True, False, []),
                          answers=_answers(rir="2-3 RIR"))
    assert preview.pending and _state(db_session, mesocycle) == before  # nothing applied

    with patch("app.routers.generation.justify_rule", return_value=_rule(db_session)), \
         patch("app.routers.generation.generate_for_movement", side_effect=_answers(rir="2-3 RIR")):
        applied = confirm_swap(db_session, user, preview.change_id)
    assert not applied.pending and applied.changes == preview.changes

    undone = undo_change(change_id=applied.change_id, db=db_session, current_user=user)
    assert undone.status == "undone"
    assert _state(db_session, mesocycle) == before  # exercises, values and schemes all restored


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_confirm_is_refused_when_the_block_changed_after_the_preview(
    _verify, db_session, owner_and_prescription,
):
    user, prescription = owner_and_prescription
    preview, _, _ = _swap(db_session, user, prescription.exercise_slot, "Dumbbell Bench Press",
                          classify=(True, True, []), answers=_answers(reps="8-12", rir="1-2 RIR"))
    prescription.sets = prescription.sets + 1  # an edit after the preview
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        confirm_swap(db_session, user, preview.change_id)
    assert exc_info.value.status_code == 409 and "preview the swap again" in exc_info.value.detail


@patch("app.routers.generation.verify_citation", return_value="primary_support")
def test_a_preview_can_be_cancelled_but_not_by_someone_else(_verify, db_session, owner_and_prescription, other_user):
    user, prescription = owner_and_prescription
    preview, _, _ = _swap(db_session, user, prescription.exercise_slot, "Dumbbell Bench Press",
                          classify=(True, True, []), answers=_answers(reps="8-12", rir="1-2 RIR"))

    with pytest.raises(HTTPException) as exc_info:
        cancel_change(change_id=preview.change_id, db=db_session, current_user=other_user)
    assert exc_info.value.status_code == 404
    cancel_change(change_id=preview.change_id, db=db_session, current_user=user)
    assert db_session.get(models.ChangeRecord, preview.change_id) is None


@patch("app.routers.generation.verify_citation", return_value="contradicted")
@patch("app.routers.chat.route_chat_message")
def test_chat_changes_undo_latest_first(mock_route, _verify, db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    prescription.sets = 3
    db_session.commit()

    def set_sets(n):
        mock_route.return_value = SimpleNamespace(
            tool="adjust_prescription", field_id=prescription.id, target_field="sets",
            adjustment_kind="set_value", requested_value=str(n), requested_change=f"make it {n} sets",
            question=None, topic=None,
        )
        from unittest.mock import MagicMock
        generate = MagicMock(return_value=(SimpleNamespace(sets=n, chunk_ids=[], grounding="general_knowledge"), []))
        with patch.dict("app.routers.chat._ADJUST_FIELDS", {"sets": (generate, lambda m, g: "q")}):
            return send_chat_message(
                request=schemas.ChatMessageRequest(message=f"make it {n} sets", field_id=prescription.id),
                db=db_session, current_user=user,
            )

    first = set_sets(4)
    second = set_sets(2)
    with pytest.raises(HTTPException) as exc_info:
        undo_change(change_id=first.change_id, db=db_session, current_user=user)
    assert exc_info.value.status_code == 409  # the later change must be undone first

    undo_change(change_id=second.change_id, db=db_session, current_user=user)
    db_session.expire_all()
    assert db_session.get(models.WeeklyPrescription, prescription.id).sets == 4
    undo_change(change_id=first.change_id, db=db_session, current_user=user)
    db_session.expire_all()
    assert db_session.get(models.WeeklyPrescription, prescription.id).sets == 3
