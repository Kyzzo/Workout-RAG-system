# How many repetitions to failure are possible at a given %1RM - the link
# between a strength exercise's load, reps and RIR, which are otherwise
# generated (and cited) independently and didn't fit together: "1-5 reps at
# 80% 1RM, 1-2 RIR" when ~10 reps are possible at 80%.
#
# Mean repetitions to failure from Nuzzo et al. 2024 (Sports Med 54:303-321),
# transcribed from the tables in its Fig. 2 (main model - all exercises other
# than the two below), Fig. 3 (bench press) and Fig. 4 (leg press), the 50-95%
# 1RM rows; lighter loads are outside what this app prescribes and less
# precisely estimated. The figures are images, so the cited rule
# (rule_justifications "reps_at_percent_1rm") is verified against the values
# the paper's text states (~5 reps at 90% and ~15 at 70% for the main model;
# 8.8 and 14.1 on the bench press and 13.1 and 19.0 on the leg press at 80%
# and 70%), which these rows match. Values between the 5% rows are
# interpolated linearly - a convention, not the paper's model.
import math
import re

_MAIN = {
    95: 3.28, 90: 4.94, 85: 7.15, 80: 9.75, 75: 12.37, 70: 14.80,
    65: 17.11, 60: 19.53, 55: 22.43, 50: 25.99,
}
_BENCH_PRESS = {
    95: 2.59, 90: 4.11, 85: 6.23, 80: 8.82, 75: 11.51, 70: 14.08,
    65: 16.59, 60: 19.34, 55: 22.79, 50: 27.25,
}
_LEG_PRESS = {
    95: 7.04, 90: 8.69, 85: 10.69, 80: 13.05, 75: 15.79, 70: 18.96,
    65: 22.59, 60: 26.74, 55: 31.47, 50: 36.86,
}
MIN_PERCENT, MAX_PERCENT = 50.0, 95.0

# No meaningful %1RM: the load is the lifter's body, so effort is set by reps
# and RIR alone. A name list (a convention), checked before any % is derived.
_BODYWEIGHT = re.compile(
    r"pull-?up|chin-?up|push-?up|\bdips?\b|plank|hyperextension|back extension|sit-?up|crunch"
    r"|hanging (?:leg|knee) raise|inverted row|nordic",
    re.IGNORECASE,
)


def is_bodyweight(exercise_name: str) -> bool:
    return bool(_BODYWEIGHT.search(exercise_name))


def _table(exercise_name: str) -> dict[int, float]:
    # The paper's separate tables: barbell/Smith bench press (pooled in the
    # paper) and leg press. Dumbbell, incline and decline variants weren't
    # what it tested, so they use the main model like every other exercise.
    name = exercise_name.lower()
    if "leg press" in name:
        return _LEG_PRESS
    if "bench press" in name and not re.search(r"dumbbell|incline|decline", name):
        return _BENCH_PRESS
    return _MAIN


def table_name(exercise_name: str) -> str:
    return {id(_LEG_PRESS): "leg press", id(_BENCH_PRESS): "bench press"}.get(id(_table(exercise_name)), "main")


def reps_to_failure(percent: float, exercise_name: str) -> float:
    """Mean repetitions to failure at `percent` %1RM (clamped to 50-95%)."""
    table = _table(exercise_name)
    p = min(max(percent, MIN_PERCENT), MAX_PERCENT)
    low = int(p // 5 * 5)
    if low == p:
        return table[low]
    return table[low] + (table[low + 5] - table[low]) * (p - low) / 5


def percent_for_reps(reps: float, exercise_name: str) -> float:
    """The %1RM at which `reps` repetitions to failure are possible on
    average (clamped to 50-95%), rounded to the nearest 0.5%."""
    table = _table(exercise_name)
    rows = sorted(table.items(), reverse=True)  # heaviest (fewest reps) first
    if reps <= rows[0][1]:
        return MAX_PERCENT
    if reps >= rows[-1][1]:
        return MIN_PERCENT
    for (p_heavy, r_heavy), (p_light, r_light) in zip(rows, rows[1:]):
        if r_heavy <= reps <= r_light:
            percent = p_heavy - (reps - r_heavy) / (r_light - r_heavy) * (p_heavy - p_light)
            return round(percent * 2) / 2
    raise AssertionError("unreachable")


def min_reps_within_table(exercise_name: str, rir: float) -> int:
    """The fewest reps that can end at `rir` reps in reserve at the table's
    heaviest load (95% 1RM). On the leg press ~7 reps to failure remain even
    at 95%, so a 4-rep target at 1-2 RIR is impossible to estimate a load for;
    elsewhere it's 1-2 reps and never binds."""
    return max(1, math.ceil(reps_to_failure(MAX_PERCENT, exercise_name) - rir))


def top_of_range(reps: str) -> int | None:
    """'1-5' -> 5, '8' -> 8; None if there's no number."""
    numbers = [int(n) for n in re.findall(r"\d+", reps)]
    return max(numbers) if numbers else None


def rir_midpoint(rir: str) -> float | None:
    """'1-2 RIR' -> 1.5, '0 RIR (to failure)' -> 0; None if there's no number."""
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", rir)]
    return sum(numbers[:2]) / len(numbers[:2]) if numbers else None


# --- Do a prescription's reps, load and RIR fit together? Used to flag a
# mismatch (e.g. after a chat change to one of them) and to offer the two
# ways to make the other two fit it. People differ by about 2.5 reps at 80%
# 1RM, so differences of a rep or less aren't flagged.
FIT_TOLERANCE_REPS = 1.0
_PERCENT = re.compile(r"\s*(\d+(?:\.\d+)?)\s*%")


def parse_percent(load: str) -> float | None:
    match = _PERCENT.match(load or "")
    return float(match.group(1)) if match else None


def _fit(reps: str, load: str, rir: str, exercise_name: str):
    """(reps to failure at the load, top rep, RIR midpoint), or None when
    there's nothing to check: no %1RM, a bodyweight exercise, an unreadable
    value, or a load outside the table."""
    percent, top, mid = parse_percent(load), top_of_range(reps), rir_midpoint(rir)
    if None in (percent, top, mid) or is_bodyweight(exercise_name):
        return None
    if not MIN_PERCENT <= percent <= MAX_PERCENT:
        return None
    return reps_to_failure(percent, exercise_name), top, mid


def fit_note(reps: str, load: str, rir: str, exercise_name: str) -> str | None:
    """A plain explanation when the three don't fit; None when they do."""
    fit = _fit(reps, load, rir, exercise_name)
    if fit is None:
        return None
    to_failure, top, mid = fit
    in_reserve = to_failure - top
    if abs(in_reserve - mid) <= FIT_TOLERANCE_REPS:
        return None
    if round(in_reserve) < 0:
        consequence = f"{top} reps is more than most people can do there"
    else:
        consequence = f"{top} reps leaves about {round(in_reserve)} in reserve"
    return (
        f"At {load}, most people manage about {round(to_failure)} reps to failure (Nuzzo et al. 2024), "
        f"so {consequence} - not {rir}."
    )


def rebalance_options(changed: str, reps: str, load: str, rir: str, exercise_name: str) -> list[tuple[str, str, str]]:
    """When `changed` (reps, load or rir) leaves the three not fitting, the
    two ways to fit the others to it, as (field, new value, label): keep one
    of the other two and recalculate the last. Options outside the table
    (or that would change nothing) are left out."""
    if changed not in ("reps", "load", "rir") or fit_note(reps, load, rir, exercise_name) is None:
        return []
    to_failure, top, mid = _fit(reps, load, rir, exercise_name)
    options = []

    def reps_for_load():
        n = round(to_failure - mid)
        if n >= 1:
            options.append(("reps", str(n), f"Keep {rir}, change reps to {n}"))

    def rir_for_load():
        n = round(to_failure - top)
        if n >= 0:
            options.append(("rir", f"~{n} RIR", f"Keep {reps} reps, change RIR to ~{n}"))

    def load_for_reps_and_rir():
        target = top + mid
        table = _table(exercise_name)
        if table[int(MAX_PERCENT)] <= target <= table[int(MIN_PERCENT)]:
            percent = percent_for_reps(target, exercise_name)
            kept = f"{reps} reps" if changed == "rir" else rir
            options.append(("load", f"{percent:g}% 1RM", f"Keep {kept}, change load to {percent:g}% 1RM"))

    if changed == "load":
        reps_for_load()
        rir_for_load()
    elif changed == "reps":
        load_for_reps_and_rir()
        rir_for_load()
    else:
        load_for_reps_and_rir()
        reps_for_load()
    current = {"reps": reps, "load": load, "rir": rir}
    return [o for o in options if o[1] != current[o[0]]]
