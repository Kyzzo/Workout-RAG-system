from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.rag import generate


@pytest.fixture(autouse=True)
def similarity_order(request, monkeypatch):
    # Retrieval tests check the search + diversity logic in similarity order;
    # tests named *rerank* exercise the reranker itself.
    if "rerank" not in request.node.name:
        monkeypatch.setattr(generate, "_rerank", lambda question, candidates: candidates)


def _chunk(cid, source, score, text=None, category="volume"):
    return {"id": cid, "text": text or f"finding {cid}", "source": source, "category": category, "score": score}


_BIBLIOGRAPHY = (
    "12. Smith J. Volume and growth. J Strength Cond Res. 2019;33(4):1-9. doi: 10.1/x "
    "13. Lee K. Sets per week. Sports Med. 2020;50(2):3-8. doi: 10.1/y"
)


class _FakeStorage:
    def __init__(self, by_category, unfiltered, per_source=()):
        self.by_category, self.unfiltered, self.filters = by_category, unfiltered, []
        self.per_source = list(per_source)

    def search_per_source(self, vector, per_source, sources, query_filter=None):
        return list(self.per_source)

    def search(self, vector, top_k=5, query_filter=None):
        if query_filter is None:
            return self.unfiltered[:top_k]
        category = query_filter.must[0].match.value
        self.filters.append(category)
        return self.by_category.get(category, [])[:top_k]


def _retrieve(topic, storage):
    with patch.object(generate, "embed_texts", return_value=[[0.0]]), \
         patch.object(generate, "QdrantStorage", return_value=storage):
        return generate._retrieve_general_chunks(topic)


def test_diverse_selection_caps_each_paper_then_backfills():
    # Volume used to get 3 of 5 slots from one study and none from the big
    # meta-analysis: two per paper first, best-first ...
    ranked = [_chunk(f"a{i}", "aube", 0.9 - i / 100) for i in range(4)] + [_chunk("p1", "pelland", 0.5)]

    assert [c["id"] for c in generate._select_diverse(ranked, 3)] == ["a0", "a1", "p1"]
    # ... and a small category isn't starved: leftover slots are backfilled.
    assert [c["id"] for c in generate._select_diverse(ranked, 5)] == ["a0", "a1", "a2", "a3", "p1"]


def test_diverse_selection_drops_reference_lists_and_duplicates():
    ranked = [
        _chunk("bib", "pelland", 0.9, text=_BIBLIOGRAPHY),
        _chunk("v1", "pelland", 0.8, text="growth rose with sets"),
        _chunk("v1-copy", "pelland", 0.7, text="growth  rose with\nsets"),
        _chunk("v2", "remmert", 0.6),
    ]

    assert [c["id"] for c in generate._select_diverse(ranked, 5)] == ["v1", "v2"]


def test_generation_retrieval_searches_its_category_wide_then_diversifies():
    storage = _FakeStorage(
        {"volume": [_chunk(f"a{i}", "aube", 0.9 - i / 100) for i in range(30)] + [_chunk("p1", "pelland", 0.1)]},
        [],
    )

    with patch.object(generate, "embed_texts", return_value=[[0.0]]),          patch.object(generate, "QdrantStorage", return_value=storage):
        chunks = generate._retrieve_chunks("weekly sets for chest hypertrophy", "volume")

    assert storage.filters == ["volume"]
    assert len(chunks) == generate.GENERATION_TOP_K
    assert "p1" in [c["id"] for c in chunks]  # a low-ranked second paper still gets in


def test_category_named_in_the_question_is_searched_first():
    storage = _FakeStorage(
        {"volume": [_chunk("v1", "pelland-volume", 0.5)]},
        [_chunk("r1", "rep-range-paper", 0.9, category="intensity"), _chunk("v1", "pelland-volume", 0.5)],
    )

    chunks = _retrieve("what is the optimal set range for hypertrophy", storage)

    assert storage.filters == ["volume"]
    assert [c["id"] for c in chunks] == ["v1", "r1"]  # volume finding first, the duplicate not repeated


def test_recovery_questions_search_the_recovery_category_first():
    # Recovery papers back no generated field, so only chat reaches them -
    # a damage/fatigue question searches that category before the rest.
    storage = _FakeStorage({"recovery": [_chunk("d1", "damage-paper", 0.4, category="recovery")]}, [])

    chunks = _retrieve("does less muscle damage mean more growth?", storage)

    assert storage.filters == ["recovery"]
    assert [c["id"] for c in chunks] == ["d1"]


def _scored(scores_by_index):
    parsed = SimpleNamespace(**{f"excerpt_{i}": s for i, s in scores_by_index.items()})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])


def test_rerank_orders_by_how_well_excerpts_answer_the_question():
    # The reported miss: a statistical result that answers the question
    # directly ranked below excerpts that only share its wording.
    candidates = [_chunk("title-match", "lasevicius", 0.9), _chunk("intro", "remmert", 0.8),
                  _chunk("slope-result", "pelland", 0.5)]
    with patch.object(generate.client.chat.completions, "parse", return_value=_scored({0: 6, 1: 2, 2: 9})):
        ranked = generate._rerank("is 3x better than 2x?", candidates)

    assert [c["id"] for c in ranked] == ["slope-result", "title-match", "intro"]
    assert [c["rerank_score"] for c in ranked] == [9, 6, 2]


def test_failed_rerank_keeps_similarity_order():
    candidates = [_chunk("a", "p1", 0.9), _chunk("b", "p2", 0.8)]
    with patch.object(generate.client.chat.completions, "parse", side_effect=RuntimeError("down")):
        assert generate._rerank("q", candidates) == candidates


def test_select_after_rerank_never_lets_a_weak_excerpt_displace_a_strong_one():
    # Paper A's second strong finding beats paper B's off-topic intro; the
    # weak excerpt is only used if there's room left.
    # (Similarity-order diversity alone would give a1, a2, b-intro: paper A
    # capped at 2, B's intro taking the third slot.)
    candidates = [_chunk("a1", "A", 0.9), _chunk("a2", "A", 0.8), _chunk("a3", "A", 0.75),
                  _chunk("b-intro", "B", 0.7)]
    with patch.object(generate.client.chat.completions, "parse",
                      return_value=_scored({0: 9, 1: 8, 2: 7, 3: 2})):
        assert [c["id"] for c in generate._select("q", candidates, 3)] == ["a1", "a2", "a3"]
        assert [c["id"] for c in generate._select("q", candidates, 4)] == ["a1", "a2", "a3", "b-intro"]


def test_a_paper_outside_the_top_similarity_results_still_reaches_selection():
    # The per-paper pass: the RIR meta-analyses never made a top-40 that three
    # papers' wording dominated.
    top = [_chunk(f"r{i}", "refalo-2024", 0.9 - i / 100) for i in range(5)]
    storage = _FakeStorage({}, top, per_source=[_chunk("meta", "grgic-meta", 0.3)])

    with patch.object(generate, "embed_texts", return_value=[[0.0]]),          patch.object(generate, "QdrantStorage", return_value=storage):
        chunks = generate._retrieve_chunks("how close to failure for strength?", None)

    assert "meta" in [c["id"] for c in chunks]
