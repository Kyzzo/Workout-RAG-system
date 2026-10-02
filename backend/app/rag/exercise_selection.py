# AI exercise selection for the program wizard. Unlike every other model
# output in this app, this one is NOT research-grounded or cited: the corpus
# has no exercise-selection literature, and citations attach to numbers, not
# to which exercises were picked (datamodel.txt). It's constrained instead.
#
# Coverage is structural: each day's response has one REQUIRED field per
# target muscle, so the model can't return a day with no exercise for, say,
# side delts. (An earlier version asked for a free list and checked coverage
# afterwards; with 8 targets per Upper day the model missed muscles twice in
# a row even when told what was missing.) Front delts and lower back get an
# optional field instead - pressing and hinging usually train them as a
# secondary. Picks also name secondary muscles (half a set each toward
# weekly volume).
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

from ..splits import COVERED_AS_SECONDARY_OK, MUSCLE_GROUPS, PlannedDay

load_dotenv()

client = OpenAI()

MIN_EXERCISES, MAX_EXERCISES = 4, 8
MAX_EXTRAS = 3

_SYSTEM_PROMPT = (
    "You design the exercise selection for a resistance-training program, "
    "using common gym equipment. Each training day has one field per target "
    "muscle: fill each with an exercise that MAINLY trains that muscle. "
    "Distinguish lats (vertical pulls: pulldowns, pull-ups) from upper back "
    "(horizontal pulls: rows), and side delts (lateral raises) from rear "
    "delts (reverse flyes, face pulls). Fields marked optional (front delts, "
    "lower back) should be null when another exercise that day already lists "
    "that muscle as a secondary - pressing trains front delts, hinging "
    "trains the lower back. Use extras only to bring a day to between "
    f"{MIN_EXERCISES} and {MAX_EXERCISES} exercises in total. In "
    "secondary_muscle_groups, list up to 3 other muscles an exercise "
    "meaningfully trains (e.g. a barbell row: lats, rear delts, biceps), or "
    "none for isolation work. Set is_compound for multi-joint movements. Use "
    "common names (e.g. 'Barbell Back Squat', 'Lat Pulldown'). When the same "
    "day type repeats in a week (e.g. 'Push 1' and 'Push 2'), vary the "
    "exercise choices between them rather than repeating the same list."
)


class ExerciseSelectionError(Exception):
    pass


def _field(group: str) -> str:
    return group.replace(" ", "_")


def _response_schema(days: list[PlannedDay]) -> type[pydantic.BaseModel]:
    # Secondaries may be any muscle, not just the day's targets: a row's
    # biceps work counts toward biceps volume even on a day without biceps.
    exercise = pydantic.create_model(
        "Exercise",
        exercise_name=(str, ...),
        is_compound=(bool, ...),
        secondary_muscle_groups=(list[Literal[MUSCLE_GROUPS]], ...),
    )
    day_models = {}
    for i, day in enumerate(days):
        extra = pydantic.create_model(
            f"Day{i + 1}Extra",
            exercise_name=(str, ...),
            is_compound=(bool, ...),
            muscle_group=(Literal[day.muscle_groups], ...),
            secondary_muscle_groups=(list[Literal[MUSCLE_GROUPS]], ...),
        )
        fields = {}
        for group in day.muscle_groups:
            if group in COVERED_AS_SECONDARY_OK:
                fields[_field(group)] = (
                    exercise | None,
                    pydantic.Field(description=f"Optional: an exercise mainly for {group}, or null if "
                                   "another exercise today already trains it as a secondary."),
                )
            else:
                fields[_field(group)] = (exercise, pydantic.Field(description=f"An exercise mainly for {group}."))
        fields["extras"] = (
            list[extra],
            pydantic.Field(description=f"0-{MAX_EXTRAS} additional exercises, only to reach "
                           f"{MIN_EXERCISES}-{MAX_EXERCISES} exercises for the day."),
        )
        day_models[f"day_{i + 1}"] = (
            pydantic.create_model(f"Day{i + 1}", **fields),
            pydantic.Field(description=f"'{day.name}' (targets: {', '.join(day.muscle_groups)})."),
        )
    return pydantic.create_model("ExerciseSelection", **day_models)


def _flatten(day: PlannedDay, day_response) -> list[tuple[str, str, list[str], bool]]:
    """(exercise_name, primary, secondaries, is_compound), compounds first,
    trimmed to MAX_EXERCISES deterministically rather than failing: every
    required-target exercise stays; an optional-target one (front delts,
    lower back) stays only if nothing already trains that muscle as a
    secondary; extras fill whatever room is left."""
    def pick_tuple(pick, primary):
        secondaries = _clean_secondaries(primary, pick.secondary_muscle_groups)
        return (pick.exercise_name.strip(), primary, secondaries, pick.is_compound)

    required, optional = [], []
    for group in day.muscle_groups:
        pick = getattr(day_response, _field(group), None)
        if pick is not None:
            (optional if group in COVERED_AS_SECONDARY_OK else required).append(pick_tuple(pick, group))
    extras = [pick_tuple(pick, pick.muscle_group) for pick in day_response.extras[:MAX_EXTRAS]]

    covered = {g for p in required + extras for g in p[2]}
    needed_optional = [p for p in optional if p[1] not in covered]
    redundant_optional = [p for p in optional if p[1] in covered]
    picks = required + needed_optional
    room = MAX_EXERCISES - len(picks)
    picks += (extras + redundant_optional)[:max(0, room)]

    # Stable sort: compounds before isolation, otherwise in target order.
    return sorted(picks, key=lambda p: not p[3])


def _problems(days: list[PlannedDay], selection) -> list[str]:
    problems = []
    for i, day in enumerate(days):
        picks = _flatten(day, getattr(selection, f"day_{i + 1}"))
        primaries = {p[1] for p in picks}
        secondaries = {g for p in picks for g in p[2]}
        missing = {
            g for g in day.muscle_groups
            if g not in primaries and not (g in COVERED_AS_SECONDARY_OK and g in secondaries)
        }
        if missing:
            problems.append(f"{day.name} has no exercise for {', '.join(sorted(missing))}")
        if not MIN_EXERCISES <= len(picks) <= MAX_EXERCISES:
            problems.append(f"{day.name} has {len(picks)} exercises")
    return problems


def _clean_secondaries(primary: str, secondaries: list[str]) -> list[str]:
    # Drop the primary if repeated, dedupe keeping order, cap at 3.
    seen = []
    for group in secondaries:
        if group != primary and group not in seen:
            seen.append(group)
    return seen[:3]


def select_exercises(
    days: list[PlannedDay], goal: str, split_label: str,
) -> list[list[tuple[str, str, list[str]]]]:
    """Returns, per planned day, a list of (exercise_name, primary, secondaries).

    One model call per DAY TYPE (all the Upper days together, all the Lower
    days together), run in parallel. A single call for the whole week hit
    OpenAI's limit of 1000 enum values per structured-output schema on
    6-day splits (every exercise's secondary-muscle field repeats the
    14-muscle enum). Repeated days of one type still share a call, so they
    can still vary from each other."""
    groups: dict[str, list[int]] = {}
    for i, day in enumerate(days):
        groups.setdefault(day.day_type or day.name, []).append(i)

    results: list = [None] * len(days)
    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        futures = {
            tuple(indices): pool.submit(
                _select_group, [days[i] for i in indices], goal, f"{split_label}, {len(days)} days per week",
            )
            for indices in groups.values()
        }
        for indices, future in futures.items():
            for i, picks in zip(indices, future.result()):
                results[i] = picks
    return results


def _select_group(days: list[PlannedDay], goal: str, split_description: str) -> list[list[tuple[str, str, list[str]]]]:
    schema = _response_schema(days)
    day_lines = "\n".join(f"- {d.name}: {', '.join(d.muscle_groups)}" for d in days)
    request = (
        f"Goal: {goal}. Split: {split_description}.\n"
        f"Choose exercises for these training days and their target muscle groups:\n{day_lines}"
    )

    feedback = ""
    for _ in range(2):  # one bounded retry, same policy as generation
        completion = client.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": request + feedback},
            ],
            response_format=schema,
        )
        message = completion.choices[0].message
        if message.refusal:
            raise ExerciseSelectionError(f"Model refused to select exercises: {message.refusal}")
        problems = _problems(days, message.parsed)
        if not problems:
            return [
                [(name, primary, secondaries) for name, primary, secondaries, _ in
                 _flatten(day, getattr(message.parsed, f"day_{i + 1}"))]
                for i, day in enumerate(days)
            ]
        feedback = "\n\nYour previous selection had problems - fix them: " + "; ".join(problems)

    raise ExerciseSelectionError("Exercise selection didn't cover every target muscle group: " + "; ".join(problems))
