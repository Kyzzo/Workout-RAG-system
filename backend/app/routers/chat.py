import re
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..ownership import get_owned_prescription
from ..rag.chat_routing import route_chat_message
from ..rag.generate import (
    Adjustment,
    PRESCRIPTION_SOURCE,
    answer_general_question,
    answer_prescription_discussion,
    build_intensity_query,
    build_volume_query,
    generate_intensity_load,
    generate_volume_sets,
    max_sets_per_exercise,
)
from ..rag.verification import STATEMENT_JUDGE, verify_citation, verify_summary
from .generation import (
    _GENERAL_KNOWLEDGE_NOTE,
    _SUPPORTED_STATUSES,
    _UNSUBSTANTIATED_NOTE,
    AdjustmentNotHonored,
    _generate_and_persist,
    copy_fields_to_other_weeks,
    field_pipeline,
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
    # Reps and RIR are asked per exercise; the exercise name is bound in
    # _handle_adjust (see generation.field_pipeline).
    "reps": None,
    "rir": None,
}


@router.post("/message", response_model=schemas.ChatResponse)
def send_chat_message(
    request: schemas.ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    decision = route_chat_message(request.message, request.field_id, request.history)

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


def _summary(p: models.WeeklyPrescription) -> str:
    parts = [f"{p.sets} sets", f"{p.reps or 'n/a'} reps"]
    if p.load:
        parts.append(f"{p.load} load")
    parts.append(f"{p.rir or 'n/a'} effort")
    return ", ".join(parts)


def _handle_adjust(decision, db: Session, current_user: models.User, raw_message: str) -> schemas.ChatResponse:
    if decision.field_id is None:
        raise HTTPException(
            status_code=400,
            detail="This needs to say which exercise/week it's about - try asking from that prescription's chat.",
        )
    if decision.target_field not in _ADJUST_FIELDS:
        raise HTTPException(
            status_code=400,
            detail="Couldn't tell whether this is about sets, reps, load or effort (RIR) - try being more specific.",
        )

    # Never trust the model's tool selection alone to authorize acting on
    # this field_id - re-verified against the requesting user's own
    # ownership chain exactly as every other entry point does
    # (phase6_chat_routing_concepts.txt section 3), whether field_id came
    # from anchored UI context or the model's own output.
    prescription = get_owned_prescription(decision.field_id, db, current_user)
    goal = prescription.exercise_slot.day_template.mesocycle.program.goal
    if decision.target_field == "load" and goal != "strength":
        return schemas.ChatResponse(
            mode="adjust_prescription",
            prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
            answer=(
                "Hypertrophy programs don't prescribe a load - effort is set by RIR (reps in reserve) "
                'instead. Try e.g. "take it closer to failure" or "make it 1-2 RIR".'
            ),
        )
    if _ADJUST_FIELDS[decision.target_field] is None:
        generate_fn, query_fn, use_mechanical_check = field_pipeline(
            decision.target_field, prescription.exercise_slot.exercise_name
        )
    else:
        generate_fn, query_fn, use_mechanical_check = _ADJUST_FIELDS[decision.target_field]
    adjustment = _build_adjustment(decision, prescription, raw_message)

    # Already at the per-exercise cap: more sets for this exercise isn't an
    # option generation can offer, so say so without spending a call on it.
    cap = max_sets_per_exercise(prescription.exercise_slot.day_template.mesocycle.program.goal)
    if decision.target_field == "sets" and adjustment and adjustment.kind == "increase" and prescription.sets >= cap:
        return schemas.ChatResponse(
            mode="adjust_prescription",
            prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
            answer=(
                f"Kept at {prescription.sets} sets - that's the most one exercise gets per session ({cap}). "
                f"For more {prescription.exercise_slot.muscle_group} volume, add another exercise for it, "
                f'or set an exact value (e.g. "make it {cap + 1} sets") to override the cap.'
            ),
            grounding_note=prescription.sets_grounding_note,
        )

    try:
        updated = _generate_and_persist(
            prescription, db, generate_fn, query_fn, decision.target_field, use_mechanical_check,
            adjustment=adjustment,
        )
        if goal != "strength":
            # Hypertrophy shows one prescription per exercise, the same every
            # week (progression is session-to-session, not scheduled), so an
            # adjustment applies to the whole exercise, not one week of it.
            others = [wp for wp in updated.exercise_slot.weekly_prescriptions if wp.id != updated.id]
            copy_fields_to_other_weeks(updated, others, (decision.target_field,))
            db.commit()
            db.refresh(updated)
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


def _verify_statements(question: str, parsed, sources: dict[str, dict]):
    """Checks every statement against each source it cites with the same
    judge as everything else, keeping a statement only if at least one of
    its research sources supports it AS WRITTEN (the judge rejects changed
    units, outcomes, populations or overstated findings). A statement citing
    only the prescription itself is app data, not a research claim, and is
    kept as is. A general answer's summary is judged against all of its
    sources together, since it may synthesize across them. Returns
    (kept: [(text, [supporting source dicts])], removed, summary: (text,
    [source dicts]) or None)."""
    # Every (statement, source) pair is judged in parallel: the strict judge
    # is slow per call, so an answer costs about one call of latency.
    checks = []
    for statement in parsed.statements:
        cited = list(dict.fromkeys(statement.sources))
        app_data = bool(cited) and all(src == PRESCRIPTION_SOURCE for src in cited)
        found = [] if app_data else [sources[src] for src in cited if src in sources]
        checks.append((statement.text, app_data, found))

    def judge(pair):
        text, source = pair
        return verify_citation(
            question, text, source["text"], parsed.grounding,
            use_mechanical_check=False, judge=STATEMENT_JUDGE,
        )

    summary = getattr(parsed, "summary", None)
    summary_sources = (
        [sources[src] for src in dict.fromkeys(summary.sources) if src in sources] if summary else []
    )

    pairs = [(text, source) for text, _, found in checks for source in found]
    statuses, summary_ok = [], False
    if pairs or summary_sources:
        with ThreadPoolExecutor(max_workers=min(len(pairs) + 1, 16)) as pool:
            summary_check = (
                pool.submit(verify_summary, question, summary.text, [s["text"] for s in summary_sources])
                if summary_sources else None
            )
            statuses = list(pool.map(judge, pairs))
            summary_ok = summary_check.result() if summary_check else False
    status_iter = iter(statuses)

    kept, removed = [], 0
    kept_summary = (summary.text, summary_sources) if summary_ok else None
    if summary and not summary_ok:
        removed += 1
    for text, app_data, found in checks:
        if app_data:
            kept.append((text, []))
            continue
        supporting = [source for source in found if next(status_iter) in _SUPPORTED_STATUSES]
        if supporting:
            kept.append((text, supporting))
        else:
            removed += 1
    return kept, removed, kept_summary


def _compose(kept, field_of=lambda source: None, summary=None):
    """Answer text with numbered references after each statement, and the
    matching numbered citation list (one entry per distinct source). A
    verified summary leads as its own paragraph, the statements after it
    as the evidence."""
    if summary:
        kept = [summary] + list(kept)
    numbers: dict[str, int] = {}
    citations = []
    parts = []
    for text, supporting in kept:
        refs = []
        for source in supporting:
            key = " ".join(source["text"].split())  # same excerpt under two ids -> one entry
            if key not in numbers:
                numbers[key] = len(numbers) + 1
                citations.append(schemas.ChatCitationOut(
                    title=source["source"], snippet=source["text"], field=field_of(source),
                ))
            refs.append(numbers[key])
        suffix = " " + "".join(f"[{n}]" for n in sorted(set(refs))) if refs else ""
        parts.append(text.strip() + suffix)
    if summary:
        return "\n\n".join(p for p in (parts[0], " ".join(parts[1:])) if p), citations
    return " ".join(parts), citations


def _removed_note(removed: int) -> str | None:
    if not removed:
        return None
    return (
        f"{removed} statement{'s were' if removed != 1 else ' was'} removed because the cited "
        f"source{'s' if removed != 1 else ''} didn't support {'them' if removed != 1 else 'it'} as written."
    )


def _handle_discuss(decision, db: Session, current_user: models.User, raw_message: str) -> schemas.ChatResponse:
    if decision.field_id is None:
        raise HTTPException(
            status_code=400,
            detail="This needs to say which exercise/week it's about - try asking from that prescription's chat.",
        )

    prescription = get_owned_prescription(decision.field_id, db, current_user)

    # No new retrieval: the excerpts are the prescription's stored citations
    # that already passed verification for their values (only primary/
    # contextual support rows - contradicted/unresolved were never valid
    # evidence). But the ANSWER rephrases them, and rephrasing can
    # misrepresent, so each statement is still checked against the excerpt
    # it cites before being shown.
    citation_rows = (
        prescription.sets_citations + prescription.reps_citations
        + prescription.load_citations + prescription.rir_citations
    )
    sources = {
        f"{row.field}-{row.citation.id}": {
            "id": f"{row.field}-{row.citation.id}", "text": row.citation.snippet,
            "source": row.citation.title, "field": row.field,
        }
        for row in citation_rows
    }
    question = decision.question or raw_message
    parsed = answer_prescription_discussion(question, _summary(prescription), list(sources.values()))
    kept, removed, _ = _verify_statements(question, parsed, sources)
    answer, citations = _compose(kept, field_of=lambda source: source["field"])

    notes = [
        f"{label}: {note}"
        for label, note in (
            ("Sets", prescription.sets_grounding_note), ("Reps", prescription.reps_grounding_note),
            ("Load", prescription.load_grounding_note), ("RIR", prescription.rir_grounding_note),
        )
        if note
    ]
    if _removed_note(removed):
        notes.append(_removed_note(removed))
    return schemas.ChatResponse(
        mode="discuss_prescription",
        prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
        answer=answer or "The sources on file for this prescription don't answer that question.",
        citations=citations,
        grounding_note=" ".join(notes) or None,
    )


def _attempt_general_question(topic: str):
    parsed, chunks = answer_general_question(topic)
    kept, removed, summary = _verify_statements(topic, parsed, {c["id"]: c for c in chunks})
    return parsed, kept, removed, summary


def _handle_general_question(decision, raw_message: str) -> schemas.ChatResponse:
    # Not persisted - conversational. Same bounded-retry policy as every
    # other generation path: retried once if nothing verified and the model
    # didn't already admit general_knowledge.
    topic = decision.topic or raw_message
    parsed, kept, removed, summary = _attempt_general_question(topic)
    if not kept and not summary and parsed.grounding != "general_knowledge":
        parsed, kept, removed, summary = _attempt_general_question(topic)

    answer, citations = _compose(kept, summary=summary)
    if kept or summary:
        grounding_note = _removed_note(removed)
    elif parsed.grounding == "general_knowledge":
        grounding_note = _GENERAL_KNOWLEDGE_NOTE
    else:
        grounding_note = _UNSUBSTANTIATED_NOTE
    return schemas.ChatResponse(
        mode="answer_general_question",
        # Never fall back to unverified prose: no verified statement means
        # no answer, said plainly.
        answer=answer or "The research in this app's corpus doesn't support a confident answer to that question.",
        citations=citations,
        grounding_note=grounding_note,
    )
