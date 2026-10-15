# The reps-to-failure table behind strength loads (Nuzzo et al. 2024).
import pytest

from app.rep_max import (
    is_bodyweight, percent_for_reps, reps_to_failure, rir_midpoint, table_name, top_of_range,
)


def test_table_matches_the_values_the_paper_states_in_its_text():
    # Main model ~5 at 90% and ~15 at 70%; bench press 8.8 and 14.1 and leg
    # press 13.1 and 19.0 at 80% and 70% (the rule's judge checks these).
    assert round(reps_to_failure(90, "Barbell Back Squat")) == 5
    assert round(reps_to_failure(70, "Barbell Back Squat")) == 15
    assert round(reps_to_failure(80, "Barbell Bench Press"), 1) == 8.8
    assert round(reps_to_failure(70, "Barbell Bench Press"), 1) == 14.1
    assert round(reps_to_failure(80, "Leg Press"), 1) == 13.1
    assert round(reps_to_failure(70, "Leg Press"), 1) == 19.0


def test_percent_and_reps_are_inverses_within_the_table():
    for percent in (52.5, 67.5, 80, 87.5, 92.5):
        assert percent_for_reps(reps_to_failure(percent, "Squat"), "Squat") == pytest.approx(percent, abs=0.5)


def test_outside_the_table_is_clamped():
    assert percent_for_reps(1, "Squat") == 95  # fewer reps than 95% allows
    assert percent_for_reps(60, "Squat") == 50
    assert reps_to_failure(99, "Squat") == reps_to_failure(95, "Squat")


def test_bench_and_leg_press_get_their_own_tables_and_variants_the_main_one():
    assert table_name("Barbell Bench Press") == "bench press"
    assert table_name("Smith Machine Bench Press") == "bench press"
    assert table_name("Leg Press") == "leg press"
    assert table_name("Dumbbell Bench Press") == "main"
    assert table_name("Incline Bench Press") == "main"


def test_parsing_reps_and_rir():
    assert (top_of_range("1-5"), top_of_range("8"), top_of_range("")) == (5, 8, None)
    assert (rir_midpoint("1-2 RIR"), rir_midpoint("0 RIR (to failure)"), rir_midpoint("")) == (1.5, 0.0, None)


def test_bodyweight_names():
    assert all(is_bodyweight(n) for n in ("Pull-Up", "Chin-up", "Plank", "Parallel Bar Dips", "Hyperextensions"))
    assert not any(is_bodyweight(n) for n in ("Lat Pulldown", "Barbell Row", "Dumbbell Press"))


def test_fit_note_only_when_off_by_more_than_a_rep():
    from app.rep_max import fit_note
    assert fit_note("5", "86.5% 1RM", "1-2 RIR", "Squat") is None
    assert "leaves about 10 in reserve" in fit_note("5", "70% 1RM", "1-2 RIR", "Squat")
    assert "more than most people can do" in fit_note("8", "90% 1RM", "1-2 RIR", "Squat")
    assert fit_note("5", "bodyweight", "1-2 RIR", "Pull-Up") is None
    assert fit_note("5", "45% 1RM", "~22 RIR", "Squat") is None  # off the table: can't check


def test_rebalance_keeps_one_value_and_recalculates_the_other():
    from app.rep_max import rebalance_options
    # changed RIR to failure at 70%: keep 5 reps -> 90% load, or keep 0 RIR -> 15 reps
    assert [(f, v) for f, v, _ in rebalance_options("rir", "5", "70% 1RM", "0 RIR (to failure)", "Squat")] == [
        ("load", "90% 1RM"), ("reps", "15"),
    ]
    # keeping 1 rep at 0 RIR needs more than 95% - off the table, so not offered
    assert [f for f, _, _ in rebalance_options("reps", "1", "70% 1RM", "0 RIR (to failure)", "Squat")] == ["rir"]
