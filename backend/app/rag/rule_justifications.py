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
from .generate import _retrieve_chunks
from .verification import STATEMENT_JUDGE, judge_citation


@dataclass(frozen=True)
class Rule:
    claim: str  # what the rule asserts - the thing citations must support
    query: str  # how to retrieve candidate evidence for it
    categories: tuple[str, ...]


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
    ),
    "per_session_diminishing_returns": Rule(
        claim=(
            "Hypertrophy shows diminishing returns as sets per session increase, with no detectable "
            "advantage beyond roughly 11 fractional sets for a muscle in one session, so higher weekly "
            "volumes are better spread across more sessions."
        ),
        query="Per-session set volume diminishing returns for hypertrophy and spreading weekly volume across sessions",
        categories=("volume", "frequency"),
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
        for chunk in _retrieve_chunks(rule.query, category):
            candidates.setdefault(" ".join(chunk["text"].split()), chunk)

    def judge(chunk):
        # A rule claim is prose with qualifiers, so it gets the strict judge;
        # its candidates are judged in parallel, since a first request (or a
        # fresh database) runs this pass while the user waits.
        try:
            return judge_citation(rule.query, rule.claim, chunk["text"], judge=STATEMENT_JUDGE).outcome
        except Exception:
            return "unresolved"

    chunks = list(candidates.values())
    with ThreadPoolExecutor(max_workers=max(1, min(len(chunks), 10))) as pool:
        verdicts = list(zip(chunks, pool.map(judge, chunks)))

    if record is None:
        record = models.RuleJustification(rule_key=key, claim=rule.claim)
        db.add(record)
    record.claim = rule.claim
    any_supported = any(status in models.SUPPORTED_VERIFICATION_STATUSES for _, status in verdicts)
    record.grounding_note = None if any_supported else NO_SUPPORT_NOTE
    record.rule_citations = [
        models.RuleCitation(citation_id=get_or_create_citation(db, chunk).id, verification_status=status)
        for chunk, status in verdicts
    ]
    try:
        db.commit()
    except IntegrityError:
        # Another request justified the same rule first; use its result.
        db.rollback()
        return db.query(models.RuleJustification).filter_by(rule_key=key).one()
    db.refresh(record)
    return record
