from sqlalchemy.orm import Session

from . import models
from .rag.corpus import evidence_label


def get_or_create_citation(db: Session, chunk: dict) -> models.Citation:
    # One Citation row per retrieved chunk, shared by every value or rule
    # that cites it (looked up by the chunk's Qdrant point id). The title is
    # the paper's evidence label ('Pelland et al. 2025 · meta-analysis ·
    # ...'), refreshed if the paper's tags changed since it was stored.
    title = evidence_label(chunk) or chunk["source"]
    citation = (
        db.query(models.Citation)
        .filter(models.Citation.qdrant_point_id == chunk["id"])
        .first()
    )
    if citation is None:
        citation = models.Citation(
            title=title,
            snippet=chunk["text"],
            qdrant_point_id=chunk["id"],
        )
        db.add(citation)
        db.flush()  # populate citation.id before it's used as a FK below
    elif citation.title != title:
        citation.title = title
    return citation
