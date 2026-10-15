# Excerpt kinds (app/rag/excerpt_kinds.py) are read once per chunk at
# ingestion. A wrong non-finding label hides a real result from value
# generation for good, so every failure must leave the excerpt unlabeled
# (kept) rather than guess.
from types import SimpleNamespace
from unittest.mock import patch

from app.rag import excerpt_kinds
from app.rag.verification import JudgeVerdict


def _parsed(kind):
    message = SimpleNamespace(refusal=None, parsed=excerpt_kinds.ExcerptReading(asserts="...", kind=kind))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_reference_lists_are_bibliography_without_a_model_call():
    payloads = [{"text": "Results: similar growth.", "section": "body"}, {"text": "1. Smith J...", "section": "references"}]

    with patch.object(excerpt_kinds.client.chat.completions, "parse", return_value=_parsed("own_finding")) as parse:
        excerpt_kinds.add_kinds("Paper 2024", payloads)

    assert [p["kind"] for p in payloads] == ["own_finding", "bibliography"]
    assert parse.call_count == 1


def test_an_excerpt_that_cant_be_labeled_is_stored_without_a_kind():
    payloads = [{"text": "Results: similar growth.", "section": "body"}]

    with patch.object(excerpt_kinds.client.chat.completions, "parse", side_effect=RuntimeError("down")):
        excerpt_kinds.add_kinds("Paper 2024", payloads)

    assert "kind" not in payloads[0]  # treated as a finding: kept in retrieval, still judged


def _result_check(sentence, whose):
    message = SimpleNamespace(refusal=None, parsed=excerpt_kinds._ResultCheck(result_sentence=sentence, whose=whose))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_a_no_result_label_stands_only_if_a_second_model_finds_no_result():
    # Plotkin 2022's introduction cites a 5-30+ rep hypertrophy result; the
    # first pass called it methods.
    found = _result_check("hypertrophy ... across five and 30 or more repetitions (Schoenfeld et al., 2017)", "cited")
    with patch.object(excerpt_kinds.client.chat.completions, "parse", side_effect=[_parsed("methods"), found]):
        assert excerpt_kinds.label_kinds([("Plotkin et al. 2022", "...")]) == ["cited_finding"]

    with patch.object(excerpt_kinds.client.chat.completions, "parse",
                      side_effect=[_parsed("methods"), _result_check(None, None)]):
        assert excerpt_kinds.label_kinds([("Plotkin et al. 2022", "...")]) == ["methods"]

    # A finding label is never second-guessed.
    with patch.object(excerpt_kinds.client.chat.completions, "parse", return_value=_parsed("own_finding")) as parse:
        assert excerpt_kinds.label_kinds([("Paper", "...")]) == ["own_finding"]
    assert parse.call_count == 1


def test_the_judge_reads_the_excerpt_before_it_decides():
    # Structured output fills fields in order: what the excerpt claims and
    # what kind of statement it is come before the verdict.
    assert list(JudgeVerdict.model_fields) == ["asserts", "kind", "outcome"]
