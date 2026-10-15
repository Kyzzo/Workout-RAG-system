# Undo for chat changes, rebalances and swaps, and the preview-then-confirm
# step for swaps. A change saves what it's about to overwrite (a snapshot of
# the exercises it touches - the whole block for a swap) and a fingerprint
# of the whole block right after it. Undo restores the snapshot only while
# the block still matches that fingerprint, i.e. nothing at all changed
# since - so changes undo latest-first, and an edit made elsewhere (a
# generate button, another change) can never be silently overwritten.
import datetime
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models

_VALUE_FIELDS = (
    "sets", "reps", "load", "rir",
    "sets_grounding_note", "reps_grounding_note", "load_grounding_note", "rir_grounding_note",
)
# A previewed swap is applied as previewed only shortly after.
PREVIEW_LIFETIME = datetime.timedelta(hours=1)


def _slot_state(slot: models.ExerciseSlot) -> dict:
    return {
        "exercise_name": slot.exercise_name,
        "is_compound": slot.is_compound,
        "secondary_muscle_groups": list(slot.secondary_muscle_groups),
        "weeks": {
            str(wp.id): {
                **{f: getattr(wp, f) for f in _VALUE_FIELDS},
                "citations": sorted(
                    [pc.field, pc.citation_id, pc.verification_status] for pc in wp.prescription_citations
                ),
            }
            for wp in slot.weekly_prescriptions
        },
    }


def _schemes_state(mesocycle: models.Mesocycle) -> list[dict]:
    return sorted(
        (
            {
                "muscle_group": s.muscle_group,
                "scheme": s.scheme,
                "grounding_note": s.grounding_note,
                "citations": sorted([c.citation_id, c.verification_status] for c in s.progression_scheme_citations),
            }
            for s in mesocycle.progression_schemes
        ),
        key=lambda s: s["muscle_group"],
    )


def _all_slots(mesocycle: models.Mesocycle) -> list[models.ExerciseSlot]:
    return [slot for day in mesocycle.day_templates for slot in day.exercise_slots]


def snapshot(mesocycle: models.Mesocycle, slots: list[models.ExerciseSlot] | None = None) -> dict:
    """The state a change may overwrite: the given exercises (default: every
    exercise) and, for a whole-block snapshot, the progression schemes."""
    whole = slots is None
    return {
        "slots": {str(s.id): _slot_state(s) for s in (_all_slots(mesocycle) if whole else slots)},
        "schemes": _schemes_state(mesocycle) if whole else None,
    }


def fingerprint(db: Session, mesocycle: models.Mesocycle) -> str:
    db.flush()
    db.expire(mesocycle)
    state = snapshot(mesocycle)
    state["day_ids"] = sorted(d.id for d in mesocycle.day_templates)
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def record(
    db: Session, user: models.User, mesocycle: models.Mesocycle, kind: str, description: str, before: dict,
) -> models.ChangeRecord:
    """Saves an applied change (call after making it, before committing)."""
    change = models.ChangeRecord(
        user_id=user.id, mesocycle_id=mesocycle.id, kind=kind, description=description, status="applied",
        snapshot=before, fingerprint=fingerprint(db, mesocycle),
    )
    db.add(change)
    db.flush()
    return change


def owned(db: Session, user: models.User, change_id: int) -> models.ChangeRecord:
    change = db.get(models.ChangeRecord, change_id)
    if change is None or change.user_id != user.id:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


def undo(db: Session, user: models.User, change_id: int) -> models.ChangeRecord:
    change = owned(db, user, change_id)
    if change.status == "undone":
        raise HTTPException(status_code=409, detail="This change was already undone.")
    if change.status != "applied":
        raise HTTPException(status_code=409, detail="This change was never applied.")
    mesocycle = change.mesocycle
    if fingerprint(db, mesocycle) != change.fingerprint:
        raise HTTPException(
            status_code=409,
            detail="The block has changed since - undo the later change first (or this change can no "
            "longer be undone safely).",
        )
    _restore(db, mesocycle, change.snapshot)
    change.status = "undone"
    db.commit()
    return change


def _restore(db: Session, mesocycle: models.Mesocycle, state: dict) -> None:
    slots = {str(s.id): s for s in _all_slots(mesocycle)}
    for slot_id, saved in state["slots"].items():
        slot = slots[slot_id]
        slot.exercise_name = saved["exercise_name"]
        slot.is_compound = saved["is_compound"]
        slot.secondary_muscle_groups = saved["secondary_muscle_groups"]
        weeks = {str(wp.id): wp for wp in slot.weekly_prescriptions}
        for wp_id, values in saved["weeks"].items():
            wp = weeks[wp_id]
            for field in _VALUE_FIELDS:
                setattr(wp, field, values[field])
            wp.prescription_citations = [
                models.PrescriptionCitation(citation_id=citation_id, field=field, verification_status=status)
                for field, citation_id, status in values["citations"]
            ]
    if state.get("schemes") is not None:
        mesocycle.progression_schemes.clear()
        db.flush()
        for saved in state["schemes"]:
            mesocycle.progression_schemes.append(models.ProgressionScheme(
                muscle_group=saved["muscle_group"], scheme=saved["scheme"], grounding_note=saved["grounding_note"],
                progression_scheme_citations=[
                    models.ProgressionSchemeCitation(citation_id=citation_id, verification_status=status)
                    for citation_id, status in saved["citations"]
                ],
            ))
    db.flush()


def pending_swap(
    db: Session, user: models.User, mesocycle: models.Mesocycle, description: str, choice: dict, block_fingerprint: str,
) -> models.ChangeRecord:
    change = models.ChangeRecord(
        user_id=user.id, mesocycle_id=mesocycle.id, kind="swap", description=description, status="pending",
        pending=choice, fingerprint=block_fingerprint,
    )
    db.add(change)
    db.commit()
    return change


def confirmable(db: Session, user: models.User, change_id: int) -> models.ChangeRecord:
    """A previewed swap that can still be applied exactly as previewed."""
    change = owned(db, user, change_id)
    if change.status != "pending":
        raise HTTPException(status_code=409, detail="This swap was already confirmed or cancelled.")
    if db.scalar(select(func.now())).replace(tzinfo=None) - change.created_at > PREVIEW_LIFETIME:  # database time
        raise HTTPException(status_code=409, detail="This preview has expired - preview the swap again.")
    if fingerprint(db, change.mesocycle) != change.fingerprint:
        raise HTTPException(status_code=409, detail="The block has changed since the preview - preview the swap again.")
    return change
