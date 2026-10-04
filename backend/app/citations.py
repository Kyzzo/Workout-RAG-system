from sqlalchemy.orm import Session

from . import models


def get_or_create_citation(db: Session, chunk: dict) -> models.Citation:
    # One Citation row per retrieved chunk, shared by every value or rule
    # that cites it (looked up by the chunk's Qdrant point id).
    citation = (
        db.query(models.Citation)
        .filter(models.Citation.qdrant_point_id == chunk["id"])
        .first()
    )
    if citation is None:
        citation = models.Citation(
            title=chunk["source"],
            snippet=chunk["text"],
            qdrant_point_id=chunk["id"],
        )
        db.add(citation)
        db.flush()  # populate citation.id before it's used as a FK below
    return citation
