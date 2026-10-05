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
    uv run python -m scripts.eval_retrieval
"""

import logging
import sys
from collections import Counter

from app.rag import generate as G

# (label, retrieve() -> chunks, papers that should be among them)
CASES = [
    # Generation cases ask the questions generation actually asks: volume,
    # frequency and progression once per goal (muscle_group=None); reps, RIR
    # and load per movement type.
    ("volume / hypertrophy",
     lambda: G._retrieve_chunks(G.build_volume_query(None, "hypertrophy"), "volume", "hypertrophy"),
     {"pelland-etal-2025", "weekly-sets-dose-response", "remmert-etal-2025-per-session-volume"}),
    ("volume / strength",
     lambda: G._retrieve_chunks(G.build_volume_query(None, "strength"), "volume", "strength"),
     {"pelland-etal-2025", "androulakis-korakakis-etal-2020-min-dose"}),
    ("reps / hypertrophy / compound",
     lambda: G._retrieve_chunks(G.build_movement_query("reps", "hypertrophy", "compound"), "intensity", "hypertrophy"),
     {"schoenfeld-etal-2021"}),
    ("rir / hypertrophy / isolation",
     lambda: G._retrieve_chunks(G.build_movement_query("rir", "hypertrophy", "isolation"), "intensity", "hypertrophy"),
     {"refalo-etal-2023-proximity-failure-meta", "robinson-etal-2024-proximity-to-failure",
      "refalo-etal-2024-failure-vs-rir"}),
    ("rir / strength / compound",
     lambda: G._retrieve_chunks(G.build_movement_query("rir", "strength", "compound"), "intensity", "strength"),
     {"robinson-etal-2024-proximity-to-failure", "grgic-etal-2022-failure-meta"},
     {"refalo-etal-2023-proximity-failure-meta", "refalo-etal-2024-failure-vs-rir"}),
    ("frequency / strength",
     lambda: G._retrieve_chunks(G.build_frequency_query(None, "strength"), "frequency", "strength"),
     {"pelland-etal-2025"}),
    ("progression / strength",
     lambda: G._retrieve_chunks(G.build_progression_query(None, "strength"), "progression", "strength"),
     {"zhang-etal-2026"}),
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
]


def main():
    logging.disable(logging.INFO)
    print(f"settings: generation top {G.GENERATION_TOP_K} of {G.GENERATION_CANDIDATES}, "
          f"chat top {G.GENERAL_TOP_K}, max {G.MAX_CHUNKS_PER_PAPER} per paper before backfill\n")
    found_total = expected_total = 0
    leaks = 0
    for label, retrieve, expected, *rest in CASES:
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
