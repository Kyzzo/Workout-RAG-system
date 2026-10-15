import threading
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..database import get_db
from ..rag.citation_summaries import checked_summary
from ..shared_answers import shared_key

router = APIRouter(prefix="/citations", tags=["citations"])


class CitationSummaryOut(BaseModel):
    # None: no summary passed the check - the panel shows the excerpt.
    summary: str | None


# One writer per citation: a panel's parallel opens of the same source wait
# for the first instead of paying twice. Citations that failed the check are
# remembered for this process, so reopening one doesn't pay again (a
# restart, or a new ANSWER_VERSION, gives them another try).
_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()
_failed: set[str] = set()


def _lock_for(citation_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks[citation_id]


def _stored(db: Session, key: str) -> models.SharedAnswer | None:
    return db.query(models.SharedAnswer).filter(models.SharedAnswer.key == key).first()


@router.get("/{citation_id}/summary", response_model=CitationSummaryOut)
def get_citation_summary(
    citation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """A cited excerpt in plain language (see rag/citation_summaries.py):
    written and checked against the excerpt the first time anyone opens it,
    then stored for everyone. Research excerpts are shared, not per user."""
    citation = db.get(models.Citation, citation_id)
    if citation is None:
        raise HTTPException(status_code=404, detail="Citation not found")

    key = shared_key("citation_summary", citation_id)
    with _lock_for(citation_id):
        stored = _stored(db, key)
        if stored is not None:
            return CitationSummaryOut(summary=stored.value)
        if key in _failed:
            return CitationSummaryOut(summary=None)

        summary = checked_summary(citation.title, citation.snippet)
        if summary is None:
            _failed.add(key)
            return CitationSummaryOut(summary=None)
        try:
            db.add(models.SharedAnswer(key=key, field="citation_summary", value=summary))
            db.commit()
        except IntegrityError:
            db.rollback()  # stored meanwhile by another instance
        return CitationSummaryOut(summary=summary)
