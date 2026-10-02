# Training splits for the program wizard. Deterministic structure only -
# which day types a split has, which muscle groups each day targets, and
# which days-per-week counts repeat cleanly within a week. Exercise choice
# is the AI's job (rag/exercise_selection.py); the numbers are generation's.
#
# Day counts are limited to ones where the split's day types fit an exact
# number of times into a week, because a block's days are the same every
# week (datamodel.txt: DayTemplate is fixed per mesocycle) - a rotating
# 3-day Upper/Lower (U-L-U, then L-U-L) can't be represented.
from dataclasses import dataclass


@dataclass(frozen=True)
class DayType:
    name: str
    muscle_groups: tuple[str, ...]


@dataclass(frozen=True)
class Split:
    label: str
    day_types: tuple[DayType, ...]
    allowed_days: tuple[int, ...]


# The muscle groups splits target and exercises are tagged with. Finer
# than "back"/"shoulders": vertical pulls (lats) and horizontal pulls
# (upper back) train different things, as do side and rear delts.
MUSCLE_GROUPS = (
    "chest", "lats", "upper back", "lower back",
    "front delts", "side delts", "rear delts", "biceps", "triceps",
    "quadriceps", "hamstrings", "glutes", "calves", "abs",
)

# Targets that may be covered by an exercise's SECONDARY muscles rather
# than needing a dedicated exercise: pressing already trains front delts
# and hinging already trains the lower back, so a front raise or back
# extension isn't forced into every day that lists them.
COVERED_AS_SECONDARY_OK = frozenset({"front delts", "lower back"})

_UPPER = DayType("Upper", (
    "chest", "lats", "upper back", "front delts", "side delts", "rear delts", "biceps", "triceps",
))
_LOWER = DayType("Lower", ("quadriceps", "hamstrings", "glutes", "lower back", "calves", "abs"))
_LEGS = DayType("Legs", ("quadriceps", "hamstrings", "glutes", "lower back", "calves", "abs"))

SPLITS: dict[str, Split] = {
    "upper_lower": Split("Upper/Lower", (_UPPER, _LOWER), (2, 4, 6)),
    "ppl": Split("Push/Pull/Legs", (
        DayType("Push", ("chest", "front delts", "side delts", "triceps")),
        DayType("Pull", ("lats", "upper back", "rear delts", "biceps")),
        _LEGS,
    ), (3, 6)),
    "anterior_posterior": Split("Anterior/Posterior", (
        DayType("Anterior", ("chest", "front delts", "side delts", "quadriceps", "biceps", "abs")),
        DayType("Posterior", (
            "lats", "upper back", "rear delts", "hamstrings", "glutes", "lower back", "triceps", "calves",
        )),
    ), (2, 4, 6)),
    "torso_limbs": Split("Torso/Limbs", (
        DayType("Torso", (
            "chest", "lats", "upper back", "front delts", "side delts", "rear delts", "lower back", "abs",
        )),
        DayType("Limbs", ("quadriceps", "hamstrings", "glutes", "calves", "biceps", "triceps")),
    ), (2, 4, 6)),
    "arnold": Split("Arnold", (
        DayType("Chest & Back", ("chest", "lats", "upper back")),
        DayType("Shoulders & Arms", ("front delts", "side delts", "rear delts", "biceps", "triceps")),
        _LEGS,
    ), (3, 6)),
    # FBEOD: a true every-other-day cycle (3.5 sessions/week) can't repeat
    # within a fixed week, so it's offered as 2-4 full-body days, spaced out.
    "full_body": Split("Full Body (FBEOD)", (
        DayType("Full Body", (
            "chest", "lats", "upper back", "side delts", "quadriceps", "hamstrings", "glutes",
        )),
    ), (2, 3, 4)),
}


@dataclass(frozen=True)
class PlannedDay:
    name: str
    muscle_groups: tuple[str, ...]
    rest_days_before: int | None


def plan_days(split: Split, days_per_week: int) -> list[PlannedDay]:
    """The week's sessions in order: day types cycled to fill the count,
    numbered when a type repeats ("Push 1", "Push 2"), with rest days spread
    as evenly as the week allows (3 days -> Mon/Wed/Fri)."""
    types = [split.day_types[i % len(split.day_types)] for i in range(days_per_week)]
    repeats = {t.name: types.count(t) for t in types}
    seen: dict[str, int] = {}

    # 7 - N rest days over N gaps; leftovers go to the gap that wraps from
    # the last session back to the first, so in-week spacing stays even.
    base, extra = divmod(7 - days_per_week, days_per_week)
    gaps = [base + (1 if i < extra else 0) for i in range(days_per_week)]  # gaps[0] is the wrap

    days = []
    for i, day_type in enumerate(types):
        seen[day_type.name] = seen.get(day_type.name, 0) + 1
        name = f"{day_type.name} {seen[day_type.name]}" if repeats[day_type.name] > 1 else day_type.name
        days.append(PlannedDay(name, day_type.muscle_groups, None if i == 0 else gaps[i]))
    return days
