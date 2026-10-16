import json
import logging
import queue
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import changes, models, schemas
from ..auth import get_current_user
from ..database import SessionLocal, get_db
from ..progress import report, reporting
from ..shared_answers import shared_key
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
    search_general,
)
from ..rag.corpus import evidence_label, evidence_text
from ..rag.verification import STATEMENT_JUDGE, verify_citation, verify_summary
from .generation import (
    _GENERAL_KNOWLEDGE_NOTE,
    _SUPPORTED_STATUSES,
    _UNSUBSTANTIATED_NOTE,
    AdjustmentNotHonored,
    _generate_and_persist,
    adjust_strength_load,
    preview_swap,
    copy_fields_to_other_weeks,
    field_pipeline,
    rebalance_for,
)

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

# The chat's suggested general questions (mirrors GENERAL_PROMPTS in
# frontend/app/ChatWindow.tsx). Everyone asks them word for word, so each
# one's verified answer is stored once (in shared_answers, keyed with
# ANSWER_VERSION like every shared answer) and reused: instant and free
# after the first time. Typed questions always run the full pipeline.
PRESET_GENERAL_QUESTIONS = {
    "How many sets per week should I do per muscle?",
    "How close to failure should I train?",
    "Does training a muscle 3x a week beat 2x?",
    "Should I add reps or add weight to progress?",
    "How many sets per week build strength?",
    "Do I need to train to failure to get stronger?",
    "Is undulating periodization better than linear?",
    "Should I take a deload week?",
}


def _normalize_question(text: str) -> str:
    return " ".join(text.lower().split())


_PRESET_KEYS = {_normalize_question(q) for q in PRESET_GENERAL_QUESTIONS}
_preset_locks: dict[str, threading.Lock] = {key: threading.Lock() for key in _PRESET_KEYS}

# adjust_prescription reuses Phase 4/5's own generation/verification
# pipeline unchanged (phase6_chat_routing_concepts.txt section 4) - this
# just maps the router's target_field choice onto the same (generate_fn,
# query_fn) pairs the direct REST endpoints in
# generation.py already use.
_ADJUST_FIELDS = {
    "sets": (generate_volume_sets, build_volume_query),
    "load": (generate_intensity_load, build_intensity_query),
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
    response = _respond(request, db, current_user)

    # Saved history: the message and the full response, so a reload renders
    # the conversation as it was. A failed request isn't saved.
    db.add(models.ChatMessage(
        user_id=current_user.id, role="user",
        content={"text": request.message, "anchor": request.anchor_label},
    ))
    db.add(models.ChatMessage(user_id=current_user.id, role="assistant", content=response.model_dump(mode="json")))
    db.commit()
    return response


def _respond(request: schemas.ChatMessageRequest, db: Session, current_user: models.User) -> schemas.ChatResponse:
    # A suggested general question (not about an exercise) needs no routing:
    # it's a general question, answered from the store when it can be.
    preset = _normalize_question(request.message)
    if request.field_id is None and preset in _PRESET_KEYS:
        return _answer_preset(preset, request.message, db)

    # A message from the general chat window (not opened from a
    # prescription) is usually a research question, so its evidence search
    # starts while the message is routed instead of after (~2s). Only an
    # embedding and Qdrant searches - the reranker waits for routing - so a
    # message routed elsewhere wastes a fraction of a cent.
    prefetch = None
    if request.field_id is None:
        executor = ThreadPoolExecutor(max_workers=1)
        prefetch = executor.submit(search_general, request.message)
        executor.shutdown(wait=False)

    report("Understanding your question")
    decision = route_chat_message(request.message, request.field_id, request.history)
    if decision.tool == "conversation":
        return _conversation_reply(getattr(decision, "conversation_kind", None))
    if decision.tool == "adjust_prescription":
        report("Previewing the swap" if decision.target_field == "exercise" else "Working on the change")
        return _handle_adjust(decision, db, current_user, request.message)
    if (
        decision.tool == "discuss_prescription"
        and request.field_id is None
        and getattr(decision, "field_id", None) is None
    ):
        # Discussing needs a prescription. Unanchored, the 'value' being
        # asked about is an earlier chat answer ('what is that in ordinary
        # set terms?' after a weekly-sets answer), so it's a research
        # question. The router doesn't reliably rewrite it as standalone
        # text, so the topic carries the earlier question it follows up on.
        earlier = next((t.content for t in reversed(request.history) if t.role == "user"), None)
        follow_up = decision.question or decision.topic or request.message
        decision = SimpleNamespace(topic=f"{earlier} - follow-up: {follow_up}" if earlier else follow_up)
    elif decision.tool == "discuss_prescription":
        report("Reading this prescription's sources")
        return _handle_discuss(decision, db, current_user, request.message)
    return _handle_general_question(decision, request.message, prefetch)


# Replies to a message that isn't a request (thanks, a complaint, 'huh?').
# Every message used to become a research question: 'what the fuck' after
# a set-count answer got a full research answer about volume and
# frequency (~15-20s, ~$0.11). Fixed text: no research claim, so nothing to
# cite or check, and no model call beyond routing.
_CONVERSATION_REPLIES = {
    "thanks": "Glad it helped. Ask me anything else about your training, or ask me to change a value in "
              "your program.",
    "complaint": "Sorry, that missed. Tell me what was wrong or what you wanted - ask the question again, or "
                 "say which part or unit to change - and I'll answer that directly.",
    "greeting": "Hi! I can answer training research questions - sets, reps, effort, frequency, progression - "
                "or change values in your program. What would you like?",
    "unclear": "I'm not sure what you're asking. I can answer training research questions or change values "
               "in your program - what would you like?",
}


def _conversation_reply(kind: str | None) -> schemas.ChatResponse:
    # Sent as an answer with no citations or note, so the chat shows it as
    # a plain message without a new response mode for the frontend.
    return schemas.ChatResponse(
        mode="answer_general_question", answer=_CONVERSATION_REPLIES.get(kind, _CONVERSATION_REPLIES["unclear"]),
    )


def _prefetched(prefetch: Future | None, topic: str, raw_message: str) -> list[dict] | None:
    """The early search's candidates, if they're for the question being
    answered: routing can rewrite a follow-up ('what about for strength?')
    into a different topic, and then the search runs again on that. If the
    early search failed, the normal search runs instead (and raises its own
    error if the failure wasn't a fluke)."""
    if prefetch is None or _normalize_question(topic) != _normalize_question(raw_message):
        return None
    try:
        return prefetch.result()
    except Exception:
        return None


def _answer_preset(preset: str, message: str, db: Session) -> schemas.ChatResponse:
    key = shared_key("chat", preset)
    # One at a time per question: a second asker waits for the first answer
    # instead of paying for the same pipeline run.
    with _preset_locks[preset]:
        stored = db.query(models.SharedAnswer).filter(models.SharedAnswer.key == key).first()
        if stored is not None:
            report("Found a saved answer")
            return schemas.ChatResponse.model_validate_json(stored.value)

        response = _handle_general_question(SimpleNamespace(topic=message), message)
        # Only a verified answer is stored (one with cited statements), so
        # an unlucky draw is retried by the next asker, never kept.
        if response.citations:
            try:
                with db.begin_nested():
                    db.add(models.SharedAnswer(key=key, field="chat", value=response.model_dump_json()))
            except IntegrityError:
                pass  # stored meanwhile by another instance - same answer
        return response


# The chat as a stream of newline-delimited JSON: {"type": "stage", "label"}
# as each step starts, then {"type": "result", "response"} or {"type":
# "error", "status", "detail"}. Same work and saved history as /message;
# the stages are what make a ~45s answer bearable to wait for.
_session_factory = SessionLocal


@router.post("/message/stream")
def stream_chat_message(
    request: schemas.ChatMessageRequest,
    current_user: models.User = Depends(get_current_user),
):
    user_id = current_user.id
    events: queue.Queue = queue.Queue()

    def work():
        # Its own session: the request's is closed once the response starts.
        db = _session_factory()
        try:
            with reporting(lambda label: events.put({"type": "stage", "label": label})):
                response = send_chat_message(request, db, db.get(models.User, user_id))
            events.put({"type": "result", "response": response.model_dump(mode="json")})
        except HTTPException as exc:
            events.put({"type": "error", "status": exc.status_code, "detail": exc.detail})
        except Exception:
            logger.exception("Streamed chat message failed")
            events.put({"type": "error", "status": 500, "detail": "Something went wrong answering that - please try again."})
        finally:
            db.close()
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def lines():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_HISTORY_LIMIT = 100  # turns returned on load (oldest first)


@router.get("/history", response_model=list[schemas.SavedChatTurn])
def get_chat_history(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rows = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.user_id == current_user.id)
        .order_by(models.ChatMessage.id.desc())
        .limit(_HISTORY_LIMIT)
        .all()
    )[::-1]

    def change_id(content):
        return content.get("change_id") or (content.get("swap") or {}).get("change_id")

    ids = {change_id(r.content) for r in rows if r.role == "assistant"} - {None}
    statuses = {
        c.id: c.status
        for c in db.query(models.ChangeRecord).filter(
            models.ChangeRecord.id.in_(ids), models.ChangeRecord.user_id == current_user.id,
        )
    } if ids else {}
    return [
        schemas.SavedChatTurn(
            role=r.role, content=r.content,
            change_status=(statuses.get(change_id(r.content), "cancelled")
                           if r.role == "assistant" and change_id(r.content) else None),
        )
        for r in rows
    ]


@router.delete("/history", status_code=204)
def clear_chat_history(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db.query(models.ChatMessage).filter(models.ChatMessage.user_id == current_user.id).delete()
    db.commit()
    return Response(status_code=204)


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
    if decision.target_field == "exercise":
        # A swap is previewed (what it would change, nothing applied) and
        # applied only when confirmed - see generation.preview_swap.
        prescription = get_owned_prescription(decision.field_id, db, current_user)
        swap = preview_swap(db, current_user, prescription.exercise_slot, decision.requested_value)
        return schemas.ChatResponse(
            mode="adjust_prescription",
            prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
            swap=swap,
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
    # A strength load comes from the reps-to-failure table, never a separate
    # generation that could contradict the reps and RIR; only an exact value
    # the user names is taken as given (their override).
    mesocycle = prescription.exercise_slot.day_template.mesocycle
    before = changes.snapshot(mesocycle, [prescription.exercise_slot])  # for undo
    description = f"{decision.target_field} of {prescription.exercise_slot.exercise_name}, week {prescription.week_number}"
    if decision.target_field == "load" and decision.adjustment_kind != "set_value":
        adjustment = _build_adjustment(decision, prescription, raw_message)  # None: nothing to move from
        reason = adjust_strength_load(db, prescription, adjustment.kind if adjustment else None)
        change = None if reason else changes.record(db, current_user, mesocycle, "adjust", description, before)
        db.commit()
        db.refresh(prescription)
        return schemas.ChatResponse(
            mode="adjust_prescription",
            prescription=schemas.WeeklyPrescriptionOut.model_validate(prescription),
            answer=reason,
            grounding_note=prescription.load_grounding_note,
            rebalance=None if reason else rebalance_for(prescription, "load"),
            change_id=change.id if change else None,
        )
    if _ADJUST_FIELDS[decision.target_field] is None:
        generate_fn, query_fn = field_pipeline(
            decision.target_field, prescription.exercise_slot.exercise_name
        )
    else:
        generate_fn, query_fn = _ADJUST_FIELDS[decision.target_field]
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
            prescription, db, generate_fn, query_fn, decision.target_field, adjustment=adjustment,
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
    change = changes.record(db, current_user, mesocycle, "adjust", description, before)
    db.commit()
    db.refresh(updated)
    return schemas.ChatResponse(
        mode="adjust_prescription",
        change_id=change.id,
        prescription=schemas.WeeklyPrescriptionOut.model_validate(updated),
        grounding_note=getattr(updated, f"{decision.target_field}_grounding_note"),
        # Strength only: hypertrophy has no load to fit reps and RIR to.
        rebalance=rebalance_for(updated, decision.target_field) if goal == "strength" else None,
    )


# Instruction wording a writer can echo into a prescription-only statement.
# A real answer began 'The current prescription programs 12 sets per week; a
# statement that only describes the prescription's current values may cite
# the source ID 'prescription'' - prompt text, shown unchecked.
_INSTRUCTION_ECHO = re.compile(r"source id|may cite|cite (it|them)|a statement that|the id prescription", re.I)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _states_only_prescription(text: str, prescription_values: str) -> bool:
    """Whether a statement citing only the prescription says nothing but its
    values: no echoed instruction text, and every number in it is one of the
    prescription's. A mechanical check with no model call - it can only
    drop such a statement, which isn't research anyway."""
    if _INSTRUCTION_ECHO.search(text):
        return False
    allowed = set(_NUMBER.findall(prescription_values))
    return set(_NUMBER.findall(text)) <= allowed


def _verify_statements(question: str, parsed, sources: dict[str, dict], prescription_values: str | None = None):
    """Checks every statement against each source it cites with the same
    judge as everything else, keeping a statement only if at least one of
    its research sources supports it AS WRITTEN (the judge rejects changed
    units, outcomes, populations or overstated findings). A statement citing
    only the prescription itself is app data, not a research claim: it's
    kept if it states only the prescription's values (`prescription_values`,
    see _states_only_prescription). A general answer's summary is judged against all of its
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
        return verify_citation(question, text, evidence_text(source), judge=STATEMENT_JUDGE, prose=True)

    summary = getattr(parsed, "summary", None)
    summary_sources = (
        [sources[src] for src in dict.fromkeys(summary.sources) if src in sources] if summary else []
    )

    pairs = [(text, source) for text, _, found in checks for source in found]
    to_check = sum(1 for _, _, found in checks if found) + (1 if summary_sources else 0)
    if to_check:
        report(f"Checking {to_check} statement{'' if to_check == 1 else 's'} against their sources")
    statuses, summary_ok = [], False
    if pairs or summary_sources:
        with ThreadPoolExecutor(max_workers=min(len(pairs) + 1, 16)) as pool:
            summary_check = (
                pool.submit(verify_summary, question, summary.text, [evidence_text(s) for s in summary_sources])
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
            if prescription_values is None or _states_only_prescription(text, prescription_values):
                kept.append((text, []))
            else:
                removed += 1
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
                    title=evidence_label(source), snippet=source["text"], field=field_of(source),
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
    kept, removed, _ = _verify_statements(question, parsed, sources, prescription_values=_summary(prescription))
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


def _attempt_general_question(topic: str, candidates: list[dict] | None = None):
    parsed, chunks = answer_general_question(topic, candidates)
    kept, removed, summary = _verify_statements(topic, parsed, {c["id"]: c for c in chunks})
    return parsed, kept, removed, summary


def _handle_general_question(decision, raw_message: str, prefetch: Future | None = None) -> schemas.ChatResponse:
    # Not persisted - conversational. Same bounded-retry policy as every
    # other generation path: retried once if nothing verified and the model
    # didn't already admit general_knowledge.
    topic = decision.topic or raw_message
    parsed, kept, removed, summary = _attempt_general_question(topic, _prefetched(prefetch, topic, raw_message))
    if not kept and not summary and parsed.grounding != "general_knowledge":
        report("Nothing held up against the sources - trying once more")
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
