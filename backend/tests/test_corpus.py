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


def test_text_fixes_correct_mis_mapped_symbols():
    from app.rag.corpus import TextFix
    from app.rag.data_loader import _apply_fix

    # Harries 2015's font extracts a minus sign as '2'.
    text, n = _apply_fix("(MD = 21.67 [210.88 to 7.54] kg)", TextFix(find="MD = 21.67", replace="MD = −1.67"))
    assert (text, n) == ("(MD = −1.67 [210.88 to 7.54] kg)", 1)
    # Kassiano 2022's extracts '=' as '5', fixed by a pattern.
    fix = TextFix(find=r"\b(ES|N|n)\s5\s", replace=r"\1 = ", regex=True)
    assert _apply_fix("(n 5 36); ES 5 0.62 vs 2%; ES\n5 2.54", fix) == ("(n = 36); ES = 0.62 vs 2%; ES = 2.54", 3)


def test_a_text_fix_that_stops_matching_fails_ingestion(monkeypatch):
    import pytest

    from app.rag import data_loader
    from app.rag.corpus import TextFix

    class _Page:
        def extract_text(self, **_):
            return "A clean page with no mis-mapped symbols."

    monkeypatch.setattr(data_loader, "PdfReader", lambda path: type("R", (), {"pages": [_Page()]})())
    with pytest.raises(ValueError, match="matched 0 times"):
        data_loader.load_and_chunk_pdf("paper.pdf", [TextFix(find="MD = 21.67", replace="MD = −1.67")])


def test_evidence_note_is_part_of_the_label():
    from app.rag.corpus import evidence_label

    chunk = {
        "source": "s", "citation": "Schoenfeld et al. 2016", "study_type": "meta-analysis",
        "outcome": "hypertrophy", "population": "mixed", "evidence_note": "superseded: later meta-analyses disagree",
    }
    assert evidence_label(chunk).endswith("mixed training status · superseded: later meta-analyses disagree")
