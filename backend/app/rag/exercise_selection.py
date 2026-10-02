# AI exercise selection for the program wizard. Unlike every other model
# output in this app, this one is NOT research-grounded or cited: the corpus
# has no exercise-selection literature, and citations attach to numbers, not
# to which exercises were picked (datamodel.txt). It's constrained instead:
# each pick's muscle group must be one the day actually targets, and every
# target must be covered - checked after the call, with one retry.
from typing import Literal

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

from ..splits import PlannedDay

load_dotenv()

client = OpenAI()

MIN_EXERCISES, MAX_EXERCISES = 4, 7

_SYSTEM_PROMPT = (
    "You design the exercise selection for a resistance-training program. "
    "For each training day you're given, choose between "
    f"{MIN_EXERCISES} and {MAX_EXERCISES} exercises using common gym "
    "equipment, with at least one exercise for every muscle group listed for "
    "that day, compound movements before isolation work. Tag each exercise "
    "with the single listed muscle group it mainly trains. Use common names "
    "(e.g. 'Barbell Back Squat', 'Lat Pulldown'). When the same day type "
    "repeats in a week (e.g. 'Push 1' and 'Push 2'), vary the exercise "
    "choices between them rather than repeating the same list."
)


class ExerciseSelectionError(Exception):
    pass


def _response_schema(days: list[PlannedDay]) -> type[pydantic.BaseModel]:
    # One field per day, each with its own muscle-group enum, so the model
    # can't tag a Lower-day exercise "chest" - structural, same as citing
    # only retrieved chunk ids elsewhere.
    fields = {}
    for i, day in enumerate(days):
        choice = pydantic.create_model(
            f"Day{i + 1}Exercise",
            exercise_name=(str, ...),
            muscle_group=(Literal[day.muscle_groups], ...),
        )
        fields[f"day_{i + 1}"] = (
            list[choice],
            pydantic.Field(description=f"Exercises for '{day.name}' (targets: {', '.join(day.muscle_groups)})."),
        )
    return pydantic.create_model("ExerciseSelection", **fields)


def _problems(days: list[PlannedDay], selection) -> list[str]:
    problems = []
    for i, day in enumerate(days):
        picks = getattr(selection, f"day_{i + 1}")
        missing = set(day.muscle_groups) - {p.muscle_group for p in picks}
        if missing:
            problems.append(f"{day.name} has no exercise for {', '.join(sorted(missing))}")
        if not MIN_EXERCISES <= len(picks) <= MAX_EXERCISES:
            problems.append(f"{day.name} has {len(picks)} exercises")
    return problems


def select_exercises(days: list[PlannedDay], goal: str, split_label: str) -> list[list[tuple[str, str]]]:
    """Returns, per planned day, a list of (exercise_name, muscle_group)."""
    schema = _response_schema(days)
    day_lines = "\n".join(f"- {d.name}: {', '.join(d.muscle_groups)}" for d in days)
    request = (
        f"Goal: {goal}. Split: {split_label}, {len(days)} days per week.\n"
        f"Training days and their target muscle groups:\n{day_lines}"
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
                [(p.exercise_name.strip(), p.muscle_group) for p in getattr(message.parsed, f"day_{i + 1}")]
                for i in range(len(days))
            ]
        feedback = "\n\nYour previous selection had problems - fix them: " + "; ".join(problems)

    raise ExerciseSelectionError("Exercise selection didn't cover every target muscle group: " + "; ".join(problems))
