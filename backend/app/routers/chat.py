import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..ownership import get_owned_prescription
from ..rag.chat_routing import route_chat_message
from ..rag.generate import (
    Adjustment,
    answer_general_question,
    answer_prescription_discussion,
    build_intensity_query,
    build_volume_query,
    generate_intensity_load,
    generate_volume_sets,
)
from ..rag.verification import verify_citation
from .generation import (
    _GENERAL_KNOWLEDGE_NOTE,
    _SUPPORTED_STATUSES,
    _UNSUBSTANTIATED_NOTE,
    AdjustmentNotHonored,
    _generate_and_persist,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# adjust_prescription reuses Phase 4/5's own generation/verification
# pipeline unchanged (phase6_chat_routing_concepts.txt section 4) - this
# just maps the router's target_field choice onto the same (generate_fn,
# query_fn, use_mechanical_check) triples the direct REST endpoints in
# generation.py already use.
_ADJUST_FIELDS = {
    "sets": (generate_volume_sets, build_volume_query, True),
    "load": (generate_intensity_load, build_intensity_query, False),
}


@router.post("/message", response_model=schemas.ChatResponse)
def send_chat_message(
    request: schemas.ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    decision = route_chat_message(request.message, request.field_id)

    if decision.tool == "adjust_prescription":
        return _handle_adjust(decision, db, current_user, request.message)
    if decision.tool == "discuss_prescription":
        return _handle_discuss(decision, db, current_user, request.message)
    return _handle_general_question(decision, request.message)


def _build_adjustment(decision, prescription: models.WeeklyPrescription, raw_message: str) -> Adjustment | None:
    # None means "regenerate from the research" - the original behavior,
    # still right for "update this based on the latest research".
    field = decision.target_field
    current = getattr(prescription, field)
    request = decision.requested_change or raw_message

    if decision.adjustment_kind == "set_value":
        requested = (decision.requested_value or "").strip()
        if field == "sets":
            match = re.search(r"\d+", requested)
            if not match or int(match.group()) <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Couldn't tell what number of sets you want - try e.g. \"make it 4 sets\".",
                )
            return Adjustment("set_value", request, current, int(match.group()))
        if not requested:
            raise HTTPException(
                status_code=400,
                detail="Couldn't tell what load you want - try e.g. \"make it 75% 1RM\" or \"RPE 8\".",
            )
        return Adjustment("set_value", request, current, requested)

    if decision.adjustment_kind in ("increase", "decrease"):
        # Nothing generated yet means there's nothing to move up or down
        # from - generate it fresh instead.
        is_placeholder = current == 0 if field == "sets" else not current
        return None if is_placeholder else Adjustment(decision.adjustment_kind, request, current)

    return None


def _handle_adjust(decision, db: Session, current_user: models.User, raw_message: str) -> schemas.ChatResponse:
    if decision.field_id is None:
        raise HTTPException(
            status_code=400,
            detail="This needs to say which exercise/week it's about - try asking from that prescription's chat.",
        )
    if decision.target_field not in _ADJUST_FIELDS:
        raise HTTPException(
            status_code=400,
            detail="Couldn't tell whether this is about sets or load - try being more specific.",
        )

    # Never trust the model's tool selection alone to authorize acting on
    # this field_id - re-verified against the requesting user's own
    # ownership chain exactly as every other entry point does
    # (phase6_chat_routing_concepts.txt section 3), whether field_id came
    # from anchored UI context or the model's own output.
    prescription = get_owned_prescription(decision.field_id, db, current_user)
    generate_fn, query_fn, use_mechanical_check = _ADJUST_FIELDS[decision.target_field]
    adjustment = _build_adjustment(decision, prescription, raw_message)
    try:
        updated = _generate_and_persist(
            prescription, db, generate_fn, query_fn, decision.target_field, use_mechanical_check,
            adjustment=adjustment,
        )
    except AdjustmentNotHonored as kept:
        # Raised before _generate_and_persist touches the prescription or
        # its citations, so there's nothing to undo.
        direction = "higher" if adjustment.kind == "increase" else "lower"
        example = "make it 5 sets" if decision.target_field == "sets" else "make it 80% 1RM"
        return schemas.ChatResponse(
            mode="adjust_prescription",
            prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
            answer=(
                f"Kept at {kept.current_value} - the retrieved research doesn't support going "
                f"{direction} for {prescription.exercise_slot.muscle_group}. You can still set an "
                f'exact value (e.g. "{example}"); it will be applied and marked as your override.'
            ),
            grounding_note=getattr(prescription, f"{decision.target_field}_grounding_note"),
        )
    return schemas.ChatResponse(
        mode="adjust_prescription",
        prescription=schemas.WeeklyPrescriptionOut.model_validate(updated),
        grounding_note=getattr(updated, f"{decision.target_field}_grounding_note"),
    )


def _handle_discuss(decision, db: Session, current_user: models.User, raw_message: str) -> schemas.ChatResponse:
    if decision.field_id is None:
        raise HTTPException(
            status_code=400,
            detail="This needs to say which exercise/week it's about - try asking from that prescription's chat.",
        )

    prescription = get_owned_prescription(decision.field_id, db, current_user)

    # No new retrieval or citation-verification call here - reads whatever
    # the last generation call already checked and stored, per
    # phase6_chat_routing_concepts.txt section 4 ("zero marginal LLM cost
    # for the citation-checking part"). Only primary/contextual support
    # rows are surfaced, matching datamodel.txt's PrescriptionCitation
    # display rule - a contradicted/unresolved row was never valid evidence
    # to begin with, so discussing it wouldn't be either. A separate LLM
    # call still runs to actually answer the question asked (see
    # answer_prescription_discussion) - "checking" cost is zero, not the
    # whole response; returning the raw stored data with no regard for
    # what was actually asked was a real bug, not a deliberate simplification.
    citation_rows = prescription.sets_citations + prescription.load_citations
    prescription_summary = f"{prescription.sets} sets, {prescription.reps} reps, {prescription.load} load"
    # Each excerpt is labeled with the value it backs, so the answer can't
    # present a sets citation as the reason for the load (or vice versa).
    answer = answer_prescription_discussion(
        decision.question or raw_message,
        prescription_summary,
        [f"[supports the {row.field} value] {row.citation.snippet}" for row in citation_rows],
    )
    notes = [
        f"{label}: {note}"
        for label, note in (("Sets", prescription.sets_grounding_note), ("Load", prescription.load_grounding_note))
        if note
    ]
    return schemas.ChatResponse(
        mode="discuss_prescription",
        prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
        answer=answer,
        citations=[
            schemas.ChatCitationOut(title=row.citation.title, snippet=row.citation.snippet, field=row.field)
            for row in citation_rows
        ],
        grounding_note=" ".join(notes) or None,
    )


def _attempt_general_question(topic: str):
    result, chunks = answer_general_question(topic)
    chunks_by_id = {c["id"]: c for c in chunks}

    verified = []  # (chunk, status)
    any_supported = False
    for citation in result.citations:
        chunk = chunks_by_id[citation.chunk_id]  # schema-constrained, always present
        # Judged against the SPECIFIC claim this chunk was cited for, not
        # the whole answer - the whole-answer version of this check is
        # exactly what let a real, retrieved citation back a claim it
        # didn't actually support (a dataset-composition stat used to
        # imply an efficacy finding). use_mechanical_check=False always:
        # this is free text, range-containment has nothing to check it
        # against, same reasoning as load/progression scheme.
        status = verify_citation(topic, citation.supports, chunk["text"], result.grounding, use_mechanical_check=False)
        if status in _SUPPORTED_STATUSES:
            any_supported = True
        verified.append((chunk, status))
    return result, verified, any_supported


def _handle_general_question(decision, raw_message: str) -> schemas.ChatResponse:
    # Not persisted to any table - conversational, same as the Product
    # interaction model's mode 3 description in PROJECT_CONTEXT.md. Same
    # bounded-retry policy as every other generation path
    # (citation_verification.txt section 7): retried once if nothing
    # verified and the model didn't already admit general_knowledge,
    # never retried for an honest "nothing here supports this" self-report.
    topic = decision.topic or raw_message
    result, verified, any_supported = _attempt_general_question(topic)
    if not any_supported and result.grounding != "general_knowledge":
        result, verified, any_supported = _attempt_general_question(topic)

    if any_supported:
        grounding_note = None
    elif result.grounding == "general_knowledge":
        grounding_note = _GENERAL_KNOWLEDGE_NOTE
    else:
        grounding_note = _UNSUBSTANTIATED_NOTE

    # Only citations that actually survived judge verification are shown -
    # a contradicted/unresolved chunk was never valid evidence for the
    # specific claim it was attached to, same display rule as every other
    # citation surface in this app.
    citations = [
        schemas.ChatCitationOut(title=chunk["source"], snippet=chunk["text"])
        for chunk, status in verified
        if status in _SUPPORTED_STATUSES
    ]
    return schemas.ChatResponse(
        mode="answer_general_question",
        answer=result.answer,
        citations=citations,
        grounding_note=grounding_note,
    )
