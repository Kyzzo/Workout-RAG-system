# The research corpus manifest (backend/corpus/papers.json): one entry per
# paper with the facts retrieval and verification use - which categories it
# serves, what kind of study it is, which outcome it measured and in whom.
# Tags are stored on every excerpt of the paper in Qdrant, so retrieval can
# filter to a program's goal and every model that reads an excerpt sees what
# kind of evidence it is. Ingestion refuses papers that aren't listed.
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pydantic

from .types import Category

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "corpus" / "papers.json"
REPO_ROOT = MANIFEST_PATH.parents[2]

# training-study: one group followed through a program, no randomized comparison.
StudyType = Literal["meta-analysis", "randomized-trial", "review", "training-study"]
Outcome = Literal["hypertrophy", "strength", "both"]
Population = Literal["trained", "untrained", "mixed"]
Publication = Literal["journal", "preprint", "unconfirmed"]

_STUDY_TYPE_LABEL = {
    "meta-analysis": "meta-analysis",
    "randomized-trial": "randomized trial",
    "review": "review",
    "training-study": "uncontrolled training study",
}


class TextFix(pydantic.BaseModel):
    """A correction to a paper's extracted text, for PDFs whose fonts map
    symbols to the wrong characters (a minus sign extracted as '2', '='
    as '5'). Applied to each page before chunking. `min_count` is how many
    matches the paper must contain: a fix that stops matching (a new PDF
    copy, a loader change) fails ingestion instead of silently not applying."""
    find: str
    replace: str
    regex: bool = False
    min_count: int = 1
_OUTCOME_LABEL = {"hypertrophy": "hypertrophy", "strength": "strength", "both": "hypertrophy and strength"}
_POPULATION_LABEL = {"trained": "trained lifters", "untrained": "untrained participants", "mixed": "mixed training status"}


class Paper(pydantic.BaseModel):
    source: str
    citation: str
    pdf: str
    categories: list[Category] = pydantic.Field(min_length=1)
    study_type: StudyType
    outcome: Outcome
    population: Population
    year: int
    publication: Publication
    merged_from: list[str] = []
    # Appended to the evidence label every model sees, for a caveat the tags
    # can't express (a finding later meta-analyses overturned, a tiny sample).
    evidence_note: str = ""
    text_fixes: list[TextFix] = []

    @property
    def pdf_path(self) -> Path:
        return REPO_ROOT / self.pdf

    def payload(self) -> dict:
        """Tag fields stored on each of the paper's excerpts. `category` (the
        first category) is kept for code that predates `categories`."""
        return {
            "source": self.source,
            "categories": list(self.categories),
            "category": self.categories[0],
            "citation": self.citation,
            "study_type": self.study_type,
            "outcome": self.outcome,
            "population": self.population,
            "year": self.year,
            "publication": self.publication,
            "evidence_note": self.evidence_note,
        }


def evidence_label(chunk: dict) -> str:
    """How an excerpt is introduced to the writer, reranker and judge, e.g.
    'Pelland et al. 2025 · meta-analysis · hypertrophy and strength · mixed
    training status'. Falls back to the source id for untagged excerpts."""
    if not chunk.get("study_type"):
        return chunk.get("source", "")
    parts = [
        chunk.get("citation") or chunk.get("source", ""),
        _STUDY_TYPE_LABEL.get(chunk["study_type"], chunk["study_type"]),
        _OUTCOME_LABEL.get(chunk.get("outcome"), chunk.get("outcome") or ""),
        _POPULATION_LABEL.get(chunk.get("population"), chunk.get("population") or ""),
    ]
    if chunk.get("publication") == "preprint":
        parts.append("preprint")
    parts.append(chunk.get("evidence_note") or "")
    return " · ".join(p for p in parts if p)


def evidence_text(chunk: dict) -> str:
    """An excerpt as the judge sees it: labeled with what kind of evidence
    it is, so 'don't generalize a finding beyond its population or outcome'
    can be checked against the paper's tags, not guessed from the text."""
    if not chunk.get("study_type"):
        return chunk["text"]
    return f"Source: {evidence_label(chunk)}\n\n{chunk['text']}"


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Paper]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    papers = [Paper(**entry) for entry in data["papers"]]
    by_source = {paper.source: paper for paper in papers}
    if len(by_source) != len(papers):
        raise ValueError("Duplicate source id in corpus/papers.json")
    return by_source


def paper(source: str) -> Paper:
    papers = load_manifest()
    if source not in papers:
        raise KeyError(f"{source!r} isn't in corpus/papers.json - add it (with its tags) before ingesting")
    return papers[source]
