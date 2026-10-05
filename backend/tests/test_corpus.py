# The corpus manifest (corpus/papers.json) drives ingestion, outcome
# filtering and evidence labels, so a bad entry should fail here, not at
# ingestion time.
from app.rag.corpus import load_manifest, paper


def test_manifest_entries_are_valid_and_unique():
    papers = load_manifest()  # validates every tag against its allowed values

    assert papers
    for entry in papers.values():
        payload = entry.payload()
        assert payload["category"] == entry.categories[0]  # kept for pre-manifest readers
        assert entry.source not in [s for other in papers.values() if other is not entry for s in other.merged_from]


def test_unlisted_papers_are_refused():
    import pytest

    with pytest.raises(KeyError, match="corpus/papers.json"):
        paper("a-paper-nobody-tagged")
