# Citations for the app's MECHANICAL rules. The numbers a program shows are
# generated and cited one by one; the rules that turn them into a program
# (how weekly sets are split across sessions, for example) aren't generated
# at all - they're fixed conventions. Each rule here is stated as one fixed
# claim and checked against the research corpus with the same verification
# judge every generated value goes through: only excerpts the judge accepts
# are shown as support. Rules don't vary per program, so the result is
# cached in the database and re-run (refresh=True, or
# scripts/refresh_rule_justifications.py) after new papers are ingested.
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..citations import get_or_create_citation
from .corpus import evidence_text
from .generate import _retrieve_chunks
from .verification import STATEMENT_JUDGE, judge_citation


@dataclass(frozen=True)
class Rule:
    claim: str  # what the rule asserts - the thing citations must support
    query: str  # how to retrieve candidate evidence for it
    categories: tuple[str, ...]
    outcome: str | None = None  # the outcome the claim is about, if one (retrieval filter)
    # False for a claim about what a trial did: its evidence is the methods
    # section, which the reranker (rightly, for findings) scores low.
    rerank: bool = True


RULES = {
    "even_session_split": Rule(
        claim=(
            "Spreading a muscle's weekly sets evenly across its training sessions keeps per-session "
            "volume moderate, because additional sets within a single session give diminishing returns."
        ),
        query=(
            "Does splitting weekly training volume across more sessions help, given diminishing returns "
            "of per-session volume?"
        ),
        categories=("volume", "frequency"),
    ),
    # The basis of the hypertrophy volume options (VOLUME_BANDS
    # in generate.py): Minimalist is the higher-efficiency tier, Moderate
    # and Higher volume split the intermediate one.
    "volume_efficiency_tiers": Rule(
        claim=(
            "For hypertrophy, muscle growth increases with weekly sets per muscle (counted fractionally, "
            "indirect sets as half) with diminishing returns: 5-10 weekly sets is the higher-efficiency "
            "range and 11-18 weekly sets the intermediate-efficiency range."
        ),
        query="Volume efficiency tiers for hypertrophy by fractional weekly sets per muscle",
        categories=("volume",),
        outcome="hypertrophy",
    ),
    # The basis of the strength volume options (VOLUME_BANDS in generate.py).
    "strength_volume_efficiency_tiers": Rule(
        claim=(
            "For strength, gains increase with weekly sets per muscle (counted fractionally) with "
            "strong diminishing returns: 1 weekly set is the minimum effective dose, 2 sets the "
            "higher-efficiency range and 3-4 sets the intermediate range, and additional weekly sets "
            "beyond that do not consistently enhance strength gains."
        ),
        query="Volume efficiency tiers for strength gains by fractional weekly sets",
        categories=("volume",),
        outcome="strength",
    ),
    # The two halves of the hypertrophy frequency explanation shown in the
    # wizard and per muscle (hypertrophy frequency isn't generated as a
    # number: with volume matched it doesn't move growth detectably, so a
    # single "research suggests Nx" read as if other frequencies were worse).
    "frequency_matched_volume": Rule(
        claim=(
            "When weekly sets are matched, training a muscle three times per week has not produced "
            "significantly more hypertrophy than training it twice per week, and training frequency's "
            "independent effect on hypertrophy is small."
        ),
        query="Training frequency two versus three days per week with equated volume and muscle hypertrophy",
        categories=("frequency",),
        outcome="hypertrophy",
    ),
    "per_session_diminishing_returns": Rule(
        claim=(
            "Hypertrophy shows diminishing returns as sets per session increase, with no detectable "
            "advantage beyond roughly 11 fractional sets for a muscle in one session, so higher weekly "
            "volumes are better spread across more sessions."
        ),
        query="Per-session set volume diminishing returns for hypertrophy and spreading weekly volume across sessions",
        categories=("volume", "frequency"),
        outcome="hypertrophy",
    ),
    # The per-exercise set caps (_MAX_SETS_PER_EXERCISE in generate.py).
    # The cap values themselves are a design choice - the research supports
    # several sets per exercise, not a ceiling (for hypertrophy, 5 sets per
    # exercise has outgrown 1) - so each claim cites only what multiple sets
    # per exercise do, never that the cap is a limit.
    "hypertrophy_sets_per_exercise": Rule(
        claim=(
            "Performing multiple sets per exercise has produced greater muscle hypertrophy than performing "
            "a single set per exercise."
        ),
        query="Single versus multiple sets per exercise and muscle hypertrophy",
        categories=("volume",),
        outcome="hypertrophy",
    ),
    "strength_sets_per_exercise": Rule(
        claim=(
            "For maximal (1RM) strength, two to three sets per exercise have produced greater gains than a "
            "single set, and studies of up to five or six sets per exercise have not shown a clear further "
            "strength benefit."
        ),
        query="Sets per exercise dose-response for 1RM strength: 1 set versus 3 sets versus 5 sets",
        categories=("volume",),
        outcome="strength",
    ),
    # Strength programs' progression scheme is chosen from the wizard's
    # training-status answer by this rule, not generated per program.
    "periodization_by_training_status": Rule(
        claim=(
            "For maximal (1RM) strength, undulating periodization has produced larger gains than linear "
            "periodization in trained lifters, with no clear difference between the two in untrained lifters."
        ),
        query="Undulating versus linear periodization for 1RM strength in trained and untrained individuals",
        categories=("progression",),
        outcome="strength",
    ),
    # The protocol trained lifters' strength programs follow
    # (generation._apply_daily_undulation): each lift's weekly sessions at
    # 8, 6 and 4 repetitions, heaviest last.
    "daily_undulating_protocol": Rule(
        claim=(
            "In recreationally trained men, rotating 3 sets of 8, 6 and 4 repetition maximums across the "
            "three training sessions of each week produced greater strength gains than changing from 8 to "
            "6 to 4 repetition maximums every four weeks, with training volume and intensity equated."
        ),
        query="Daily undulating periodization 8, 6 and 4 repetition maximums each week versus linear periodization",
        categories=("progression",),
        outcome="strength",
    ),
    # Untrained lifters' strength programs (generation._apply_linear_periodization):
    # the trials' linear arms.
    "linear_periodization_protocol": Rule(
        claim=(
            "In trials comparing periodization models, linear periodization was programmed as three phases "
            "of 3 sets of 8, then 6, then 4 repetition maximums, moving to the next phase every three to "
            "four weeks."
        ),
        query="Linear periodization group 3 sets of 8RM then 6RM then 4RM across training weeks",
        categories=("progression",),
        outcome="strength",
    ),
    # Strength programs' accessory lifts (generation.generate_exercise).
    "strength_accessory_reps": Rule(
        claim=(
            "In a strength trial comparing linear and daily undulating periodization in trained men, the "
            "accessory exercises (biceps curls and lat pull-downs) were trained at 3 sets of 8-12 repetition "
            "maximums, while only the bench press and leg press were periodized."
        ),
        query=(
            "Training protocol: besides the periodized leg press and bench press, subjects performed biceps "
            "curls (3 x 8-12 RM) and lat pull-downs (3 x 8-12 RM)"
        ),
        categories=("progression",),
        outcome="strength",
        rerank=False,
    ),
    # Shown with it: the exact repetitions within the rotation matter less
    # than the volume (so Rhea's numbers are one tested choice, not the only one).
    "dup_rep_scheme": Rule(
        claim=(
            "In resistance-trained men, volume-equated daily undulating programs using 12, 10 and 8 "
            "repetitions or 6, 4 and 2 repetitions per session produced similar gains in squat and bench "
            "press strength and in muscle thickness."
        ),
        query="Volume-equated high-repetition versus low-repetition daily undulating programs for strength and hypertrophy",
        categories=("progression",),
    ),
    # Why the heaviest session comes last, not straight after the
    # highest-volume one.
    "dup_session_order": Rule(
        claim=(
            "In trained powerlifters, ordering each week's daily undulating sessions as hypertrophy, then "
            "power, then strength produced greater bench press strength gains than placing the strength "
            "session directly after the hypertrophy session."
        ),
        query=(
            "Modified daily undulating periodization: hypertrophy, power, strength (HPS) versus hypertrophy, "
            "strength, power (HSP) order and 1RM bench press gains in powerlifters"
        ),
        categories=("progression",),
        outcome="strength",
    ),
    # Why the undulation is daily, not weekly.
    "weekly_undulation_not_better": Rule(
        claim=(
            "Weekly undulating periodization did not produce greater strength gains than linear "
            "periodization when training volume and intensity were equated."
        ),
        query="Weekly undulating versus linear periodization strength gains with equated volume and intensity",
        categories=("progression",),
        outcome="strength",
    ),
    # Why the deload week is an opt-in rather than the default.
    "deload_week": Rule(
        claim=(
            "In resistance-trained lifters, taking one week off training partway through a 9-week program "
            "did not change muscle hypertrophy compared with training continuously, and slightly reduced "
            "gains in some strength measures."
        ),
        query="Effect of a one-week deload or training cessation on muscle hypertrophy and strength",
        categories=("recovery",),
    ),
    # The basis of the hypertrophy progression guidance (add reps, then load).
    "hypertrophy_rep_progression": Rule(
        claim=(
            "In trained lifters, progressing by adding repetitions at a fixed load produced muscle "
            "hypertrophy similar to progressing by adding load within a fixed repetition range."
        ),
        query="Progressing repetitions versus progressing load for muscle hypertrophy",
        categories=("progression",),
        outcome="hypertrophy",
    ),
    # The basis of app/rep_max.py: strength loads are estimated from the
    # prescribed reps and RIR, and progression weeks' reps (or a deload's
    # RIR) from their load.
    "reps_at_percent_1rm": Rule(
        # The paper's SD (~2.5 reps at 80% 1RM) is left out: it's in a
        # different excerpt from the 90%/70% means, and each excerpt is judged
        # alone, so the full claim was supported in 1 of 10 runs (Oct 20,
        # 2026) and a refresh dropped the rule's only citation. Without it,
        # the means excerpt states every figure: 5 of 5.
        claim=(
            "The number of repetitions that can be completed to failure falls as the load (%1RM) rises - "
            "on average about 5 repetitions at 90% 1RM and 15 at 70% 1RM - and varies between "
            "individuals."
        ),
        query="Maximal number of repetitions to failure at percentages of the one repetition maximum",
        categories=("intensity",),
    ),
    # Shown with the frequency choice for strength programs.
    "strength_frequency": Rule(
        claim=(
            "Strength gains increase with weekly training frequency, with diminishing returns at "
            "higher frequencies."
        ),
        query="Dose-response of weekly training frequency and strength gains",
        categories=("frequency",),
        outcome="strength",
    ),
}

NO_SUPPORT_NOTE = (
    "No source in the current research corpus supports this rule yet - it's applied as a convention."
)


def justify_rule(db: Session, key: str, refresh: bool = False) -> models.RuleJustification:
    rule = RULES[key]
    record = db.query(models.RuleJustification).filter_by(rule_key=key).first()
    if record is not None and not refresh:
        return record

    # Keyed by text, not chunk id: a paper ingested under two categories
    # (e.g. Remmert as both volume and frequency) has identical chunks under
    # different ids, which would otherwise show up as duplicate excerpts.
    candidates = {}
    for category in rule.categories:
        for chunk in _retrieve_chunks(rule.query, category, rule.outcome, rerank=rule.rerank):
            candidates.setdefault(" ".join(chunk["text"].split()), chunk)

    def judge(chunk):
        # A rule claim is prose with qualifiers, so it gets the strict judge;
        # its candidates are judged in parallel, since a first request (or a
        # fresh database) runs this pass while the user waits.
        try:
            return judge_citation(rule.query, rule.claim, evidence_text(chunk), judge=STATEMENT_JUDGE, prose=True).outcome
        except Exception:
            return "unresolved"

    chunks = list(candidates.values())
    with ThreadPoolExecutor(max_workers=max(1, min(len(chunks), 10))) as pool:
        verdicts = list(zip(chunks, pool.map(judge, chunks)))

    any_supported = any(status in models.SUPPORTED_VERIFICATION_STATUSES for _, status in verdicts)
    try:
        # Citations first: their lookups autoflush, which would otherwise
        # insert a new record before the commit below.
        citations = [
            models.RuleCitation(citation_id=get_or_create_citation(db, chunk).id, verification_status=status)
            for chunk, status in verdicts
        ]
        if record is None:
            record = models.RuleJustification(rule_key=key, claim=rule.claim)
            db.add(record)
        record.claim = rule.claim
        record.grounding_note = None if any_supported else NO_SUPPORT_NOTE
        record.rule_citations = citations
        db.commit()
    except IntegrityError:
        # Parallel requests (a block's progression runs per muscle at once)
        # justify an uncached rule together; the first to commit wins - on
        # the record or on a shared citation - and the rest use its result.
        db.rollback()
        existing = db.query(models.RuleJustification).filter_by(rule_key=key).first()
        if existing is None:
            raise
        return existing
    db.refresh(record)
    return record
