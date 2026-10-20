"""
Retrieval check: for each generated field and a few chat questions, does
retrieval surface the papers that should inform it? Run after ingesting
papers or changing the retrieval settings in app/rag/generate.py, and add a
case whenever a new paper should clearly be in a field's evidence.

Prints, per case, which expected papers came back, how many distinct papers
the excerpts span, and the most excerpts any one paper took - then overall
recall. Hits the real Qdrant collection and embeddings API (no generation
or judge calls).

Usage (from backend/):
    uv run python -m scripts.eval_retrieval [label-filter ...]

With filters, only cases whose label contains one of them run (e.g.
"rule:" or "/ strength") - each case costs an embedding and a few small
reranker calls, so run just the cases a change can affect.
"""

import logging
import sys
from collections import Counter

from app.rag import generate as G
from app.rag.rule_justifications import RULES


def field(field_name, query, category, goal):
    # As generation searches: a short topic for similarity, the full question for reranking.
    return lambda: G._retrieve_chunks(query, category, goal, search=G.search_text(field_name, goal))


def rule(key, category=None):
    r = RULES[key]
    return lambda: G._retrieve_chunks(r.query, category or r.categories[0], r.outcome, rerank=r.rerank)


# (label, retrieve() -> chunks, papers that should be among them)
CASES = [
    # Generation cases ask the questions generation actually asks: volume and
    # frequency once per goal (muscle_group=None); reps, RIR and load per
    # movement type. Rule cases use each rule's own query.
    ("volume / hypertrophy",
     field("weekly_sets", G.build_volume_query(None, "hypertrophy"), "volume", "hypertrophy"),
     {"pelland-etal-2025", "weekly-sets-dose-response", "remmert-etal-2025-per-session-volume",
      "baz-valle-etal-2022-volume-hypertrophy-review"}),
    ("volume / strength",
     field("weekly_sets", G.build_volume_query(None, "strength"), "volume", "strength"),
     {"pelland-etal-2025", "androulakis-korakakis-etal-2020-min-dose"}),
    ("reps / hypertrophy / compound",
     field("reps", G.build_movement_query("reps", "hypertrophy", "compound"), "intensity", "hypertrophy"),
     {"schoenfeld-etal-2021"}),
    ("rir / hypertrophy / isolation",
     field("rir", G.build_movement_query("rir", "hypertrophy", "isolation"), "intensity", "hypertrophy"),
     {"refalo-etal-2023-proximity-failure-meta", "robinson-etal-2024-proximity-to-failure",
      "refalo-etal-2024-failure-vs-rir"}),
    ("rir / strength / compound",
     field("rir", G.build_movement_query("rir", "strength", "compound"), "intensity", "strength"),
     {"robinson-etal-2024-proximity-to-failure", "grgic-etal-2022-failure-meta"},
     {"refalo-etal-2023-proximity-failure-meta", "refalo-etal-2024-failure-vs-rir"}),
    ("frequency / strength",
     field("frequency", G.build_frequency_query(None, "strength"), "frequency", "strength"),
     {"pelland-etal-2025"}),
    ("rule: periodization by training status",
     rule("periodization_by_training_status"),
     {"moesgaard-etal-2022-periodization-meta", "harries-etal-2015-linear-vs-undulating"}),
    ("rule: deload week", rule("deload_week"), {"coleman-etal-2024-deload"}),
    ("rule: daily undulating protocol",
     rule("daily_undulating_protocol"), {"rhea-etal-2002-linear-vs-daily-undulating"}),
    ("rule: linear periodization protocol", rule("linear_periodization_protocol"),
     {"rhea-etal-2002-linear-vs-daily-undulating", "buford-etal-2007-linear-daily-weekly-undulating"}),
    ("rule: strength accessory reps", rule("strength_accessory_reps"), {"rhea-etal-2002-linear-vs-daily-undulating"}),
    ("rule: dup rep scheme", rule("dup_rep_scheme"), {"klemp-etal-2016-dup-high-vs-low-reps"}),
    ("rule: dup session order", rule("dup_session_order"), {"zourdos-etal-2016-dup-session-order"}),
    ("rule: weekly undulation not better",
     rule("weekly_undulation_not_better"),
     {"apel-etal-2011-linear-vs-weekly-undulating", "buford-etal-2007-linear-daily-weekly-undulating"}),
    ("rule: hypertrophy rep progression",
     rule("hypertrophy_rep_progression"), {"plotkin-etal-2022-load-vs-reps-progression"}),
    ("rule: reps at percent 1RM", rule("reps_at_percent_1rm"), {"nuzzo-etal-2024-reps-at-percent-1rm"}),
    ("rule: strength frequency",
     rule("strength_frequency"), {"pelland-etal-2025", "grgic-etal-2018-frequency-strength-meta"}),
    ("chat: optimal weekly sets for hypertrophy",
     lambda: G._retrieve_general_chunks("What is the optimal number of weekly sets per muscle for hypertrophy?"),
     {"pelland-etal-2025", "remmert-etal-2025-per-session-volume", "weekly-sets-dose-response"}),
    ("chat: set range wording",
     lambda: G._retrieve_general_chunks("what is the most optimal set range per muscle group for hypertrophy"),
     {"pelland-etal-2025", "remmert-etal-2025-per-session-volume"}),
    ("chat: 3x vs 2x frequency",
     lambda: G._retrieve_general_chunks("Is training a muscle 3 times a week better than 2 times for hypertrophy?"),
     {"lasevicius-etal-2019-2x-vs-3x", "pelland-etal-2025"}),
    ("rule: frequency with matched volume",
     lambda: G._retrieve_chunks(
         "Training frequency two versus three days per week with equated volume and muscle hypertrophy", "frequency"),
     {"lasevicius-etal-2019-2x-vs-3x"}),
    # Outcome filtering (optional 4th element: papers that must NOT appear):
    # hypertrophy-only papers stay out of strength questions.
    ("chat: strength question (outcome filter)",
     lambda: G._retrieve_general_chunks("How close to failure should I train for strength?"),
     {"robinson-etal-2024-proximity-to-failure"},
     {"refalo-etal-2023-proximity-failure-meta", "refalo-etal-2024-failure-vs-rir"}),
    ("chat: proximity to failure",
     lambda: G._retrieve_general_chunks("how close to failure should I train for hypertrophy"),
     {"refalo-etal-2023-proximity-failure-meta", "robinson-etal-2024-proximity-to-failure"}),
    # Papers added 2026-10-14.
    ("reps / strength / compound",
     field("reps", G.build_movement_query("reps", "strength", "compound"), "intensity", "strength"),
     {"lopez-etal-2021-load-network-meta", "schoenfeld-etal-2017-low-vs-high-load"}),
    ("reps / hypertrophy / isolation (load spectrum)",
     field("reps", G.build_movement_query("reps", "hypertrophy", "isolation"), "intensity", "hypertrophy"),
     {"lopez-etal-2021-load-network-meta", "schoenfeld-etal-2017-low-vs-high-load"}),
    ("rule: strength frequency with matched volume",
     lambda: G._retrieve_chunks(
         "Effect of training frequency on strength gains when weekly volume is equated", "frequency", "strength"),
     {"grgic-etal-2018-frequency-strength-meta", "pelland-etal-2025"},
     {"schoenfeld-etal-2016-frequency-hypertrophy-meta"}),
    ("chat: linear vs undulating periodization",
     lambda: G._retrieve_general_chunks("Is undulating periodization better than linear periodization for strength?"),
     {"moesgaard-etal-2022-periodization-meta", "harries-etal-2015-linear-vs-undulating"}),
    ("chat: add reps or weight",
     lambda: G._retrieve_general_chunks("Should I add reps or add weight to progress for muscle growth?"),
     {"plotkin-etal-2022-load-vs-reps-progression"}),
    # The failure-vs-non-failure meta-analyses, not Pareja-Blanco 2017 (one
    # 22-person trial framed as velocity loss), are what this should find.
    ("chat: failure for strength",
     lambda: G._retrieve_general_chunks("Do I need to train to failure to get stronger on squats?"),
     {"grgic-etal-2022-failure-meta", "robinson-etal-2024-proximity-to-failure"}),
    ("chat: at least 10 sets per week",
     lambda: G._retrieve_general_chunks("Do I need at least 10 sets per muscle per week to maximize growth?"),
     {"schoenfeld-etal-2017-volume-dose-response", "pelland-etal-2025"}),
    ("chat: soreness and growth",
     lambda: G._retrieve_general_chunks("Does muscle damage or soreness mean my muscles are growing?"),
     {"damas-etal-2016-damage-mps-hypertrophy"}),
    ("chat: deload week",
     lambda: G._retrieve_general_chunks("Should I take a deload week off training every few weeks?"),
     {"coleman-etal-2024-deload"}),
    # Papers added 2026-10-19. The single-vs-multiple-set meta-analyses back
    # the sets-per-exercise rules, not weekly volume: the dose-response
    # meta-analyses rightly outrank them there (rerank 4-5 vs 8+).
    ("rule: hypertrophy sets per exercise", rule("hypertrophy_sets_per_exercise"),
     {"krieger-2010-single-vs-multiple-sets-hypertrophy-meta"}),
    ("rule: strength sets per exercise", rule("strength_sets_per_exercise"),
     {"krieger-2009-single-vs-multiple-sets-meta", "schoenfeld-etal-2019-sets-per-exercise"}),
    ("chat: varying exercises",
     lambda: G._retrieve_general_chunks("Should I vary my exercises to grow more muscle?"),
     {"kassiano-etal-2022-exercise-variation-review"}),
]


def main():
    logging.disable(logging.INFO)
    print(f"settings: generation top {G.GENERATION_TOP_K} of {G.GENERATION_CANDIDATES}, "
          f"chat top {G.GENERAL_TOP_K}, max {G.MAX_CHUNKS_PER_PAPER} per paper before backfill\n")
    found_total = expected_total = 0
    leaks = 0
    filters = sys.argv[1:]
    for label, retrieve, expected, *rest in CASES:
        if filters and not any(f in label for f in filters):
            continue
        excluded = rest[0] if rest else set()
        chunks = retrieve()
        papers = Counter(c["source"] for c in chunks)
        found = expected & papers.keys()
        leaked = excluded & papers.keys()
        leaks += len(leaked)
        found_total += len(found)
        expected_total += len(expected)
        status = "ok  " if found == expected and not leaked else "MISS"
        print(f"{status} {label}: {len(found)}/{len(expected)} expected | {len(chunks)} excerpts from "
              f"{len(papers)} papers, max {max(papers.values(), default=0)} from one")
        for paper in sorted(expected - found):
            print(f"       missing: {paper}")
        for paper in sorted(leaked):
            print(f"       should not appear: {paper}")
    print(f"\nrecall: {found_total}/{expected_total} expected papers retrieved")
    if leaks:
        print(f"{leaks} paper(s) appeared where they shouldn't")
    return 0 if found_total == expected_total and not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
