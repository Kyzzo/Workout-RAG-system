# Undo for chat changes, rebalances and swaps; confirm or cancel for a
# previewed swap. See app/changes.py.
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import changes, models, schemas
from ..auth import get_current_user
from ..database import get_db
from .generation import confirm_swap

router = APIRouter(prefix="/changes", tags=["changes"])


@router.post("/{change_id}/undo", response_model=schemas.ChangeOut)
def undo_change(
    change_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return changes.undo(db, current_user, change_id)


@router.post("/{change_id}/confirm", response_model=schemas.SwapExerciseResponse)
def confirm_change(
    change_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return confirm_swap(db, current_user, change_id)


@router.delete("/{change_id}", status_code=204)
def cancel_change(
    change_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Only a preview can be cancelled; an applied change is undone instead.
    change = changes.owned(db, current_user, change_id)
    if change.status != "pending":
        raise HTTPException(status_code=409, detail="Only a previewed swap can be cancelled - undo an applied change.")
    db.delete(change)
    db.commit()
    return Response(status_code=204)
