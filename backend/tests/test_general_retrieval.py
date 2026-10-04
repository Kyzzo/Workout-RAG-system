from unittest.mock import patch

from app.rag import generate


def _chunk(cid, source, score, text=None, category="volume"):
    return {"id": cid, "text": text or f"finding {cid}", "source": source, "category": category, "score": score}


_BIBLIOGRAPHY = (
    "12. Smith J. Volume and growth. J Strength Cond Res. 2019;33(4):1-9. doi: 10.1/x "
    "13. Lee K. Sets per week. Sports Med. 2020;50(2):3-8. doi: 10.1/y"
)


class _FakeStorage:
    def __init__(self, by_category, unfiltered):
        self.by_category, self.unfiltered, self.filters = by_category, unfiltered, []

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


def test_caps_each_paper_and_drops_reference_lists():
    one_paper = [_chunk(f"r{i}", "rep-range-paper", 0.9 - i / 100, category="intensity") for i in range(6)]
    storage = _FakeStorage({}, one_paper + [
        _chunk("bib", "pelland", 0.8, text=_BIBLIOGRAPHY), _chunk("v1", "pelland", 0.7),
    ])

    chunks = _retrieve("what should I do?", storage)

    assert [c["id"] for c in chunks] == ["r0", "r1", "r2", "v1"]  # 3 per paper, bibliography skipped


def test_category_named_in_the_question_is_searched_first():
    storage = _FakeStorage(
        {"volume": [_chunk("v1", "pelland-volume", 0.5)]},
        [_chunk("r1", "rep-range-paper", 0.9, category="intensity"), _chunk("v1", "pelland-volume", 0.5)],
    )

    chunks = _retrieve("what is the optimal set range for hypertrophy", storage)

    assert storage.filters == ["volume"]
    assert [c["id"] for c in chunks] == ["v1", "r1"]  # volume finding first, the duplicate not repeated
