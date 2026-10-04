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
    ("volume / hypertrophy / chest",
     lambda: G._retrieve_chunks(G.build_volume_query("chest", "hypertrophy"), "volume"),
     {"pelland-etal-2025-volume", "weekly-sets-dose-response", "remmert-etal-2025-per-session-volume"}),
    ("volume / hypertrophy / quadriceps",
     lambda: G._retrieve_chunks(G.build_volume_query("quadriceps", "hypertrophy"), "volume"),
     {"pelland-etal-2025-volume", "aube-etal-2022-volume"}),
    ("volume / strength / quadriceps",
     lambda: G._retrieve_chunks(G.build_volume_query("quadriceps", "strength"), "volume"),
     {"pelland-etal-2025-volume", "androulakis-korakakis-etal-2020-min-dose"}),
    ("reps / hypertrophy / bench",
     lambda: G._retrieve_chunks(G.build_reps_query("chest", "hypertrophy", "Barbell Bench Press"), "intensity"),
     {"schoenfeld-etal-2021"}),
    ("rir / hypertrophy / lateral raise",
     lambda: G._retrieve_chunks(G.build_rir_query("side delts", "hypertrophy", "Lateral Raise"), "intensity"),
     {"refalo-etal-2023-proximity-failure-meta", "robinson-etal-2024-proximity-to-failure",
      "refalo-etal-2024-failure-vs-rir"}),
    ("rir / strength / bench",
     lambda: G._retrieve_chunks(G.build_rir_query("chest", "strength", "Barbell Bench Press"), "intensity"),
     {"robinson-etal-2024-proximity-to-failure", "grgic-etal-2022-failure-meta"}),
    ("frequency / hypertrophy / lats",
     lambda: G._retrieve_chunks(G.build_frequency_query("lats", "hypertrophy"), "frequency"),
     {"pelland-etal-2025-frequency", "remmert-etal-2025-per-session-volume-frequency"}),
    ("progression / strength / chest",
     lambda: G._retrieve_chunks(G.build_progression_query("chest", "strength"), "progression"),
     {"zhang-etal-2026"}),
    ("chat: optimal weekly sets for hypertrophy",
     lambda: G._retrieve_general_chunks("What is the optimal number of weekly sets per muscle for hypertrophy?"),
     {"pelland-etal-2025-volume", "remmert-etal-2025-per-session-volume", "weekly-sets-dose-response"}),
    ("chat: set range wording",
     lambda: G._retrieve_general_chunks("what is the most optimal set range per muscle group for hypertrophy"),
     {"pelland-etal-2025-volume", "remmert-etal-2025-per-session-volume"}),
    ("chat: proximity to failure",
     lambda: G._retrieve_general_chunks("how close to failure should I train for hypertrophy"),
     {"refalo-etal-2023-proximity-failure-meta", "robinson-etal-2024-proximity-to-failure"}),
]


def main():
    logging.disable(logging.INFO)
    print(f"settings: generation top {G.GENERATION_TOP_K} of {G.GENERATION_CANDIDATES}, "
          f"chat top {G.GENERAL_TOP_K}, max {G.MAX_CHUNKS_PER_PAPER} per paper before backfill\n")
    found_total = expected_total = 0
    for label, retrieve, expected in CASES:
        chunks = retrieve()
        papers = Counter(c["source"] for c in chunks)
        found = expected & papers.keys()
        found_total += len(found)
        expected_total += len(expected)
        status = "ok  " if found == expected else "MISS"
        print(f"{status} {label}: {len(found)}/{len(expected)} expected | {len(chunks)} excerpts from "
              f"{len(papers)} papers, max {max(papers.values(), default=0)} from one")
        for paper in sorted(expected - found):
            print(f"       missing: {paper}")
    print(f"\nrecall: {found_total}/{expected_total} expected papers retrieved")
    return 0 if found_total == expected_total else 1


if __name__ == "__main__":
    sys.exit(main())
