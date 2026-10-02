from typing import Literal

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

# The three modes from notes/phase6/phase6_chat_routing_concepts.txt
# section 1, exposed as a fixed menu the model must choose from - a
# materially more constrained decision than open-ended generation, same
# "structural constraint over trusted free text" instinct as constraining
# chunk_ids to an enum (citation_verification.txt section 2). Mis-routing
# is a real, accepted residual risk (section 2), bounded to this fixed set
# of outcomes rather than eliminated.
ChatTool = Literal["adjust_prescription", "discuss_prescription", "answer_general_question"]

_ROUTER_SYSTEM_PROMPT = (
    "You are routing a user's chat message in a workout-program-structuring "
    "app to exactly one of three tools:\n"
    "- adjust_prescription: the user wants a specific prescribed value "
    "(sets or load) for a specific exercise/week changed or regenerated, "
    "e.g. 'add more volume for my squats' or 'update my bench load based "
    "on the latest research'. Also set target_field to whichever of "
    "'sets' (how many sets), 'reps' (the rep range), 'load' (weight as "
    "%1RM) or 'rir' (effort: reps in reserve - 'closer to failure' / "
    "'harder' means DECREASE rir, 'further from failure' / 'easier' means "
    "increase it) the "
    "request is actually about, and adjustment_kind to what's being asked: "
    "'set_value' if the user names an exact value (also put that value in "
    "requested_value, e.g. '4' for sets or '75% 1RM' / 'RPE 8' for load), "
    "'increase' or 'decrease' for a direction without an exact value "
    "('more volume', 'go lighter'), or 'regenerate' to just redo it from the "
    "research ('update based on the latest research').\n"
    "- discuss_prescription: the user is asking ABOUT a specific already-"
    "generated value without asking to change it, e.g. 'why is this 8-10 "
    "reps' or 'what's the evidence behind this'.\n"
    "- answer_general_question: a free-standing research question not "
    "about one specific prescribed value, e.g. 'what does research say "
    "about training to failure'.\n"
    "If the message is already anchored to a specific field (you'll be "
    "told so explicitly), assume adjust_prescription or "
    "discuss_prescription unless the message clearly asks something "
    "unrelated to that field.\n"
    "You may be shown the earlier conversation. Use it ONLY to work out "
    "what the new message refers to (e.g. 'ok lower it' after discussing a "
    "set count means decrease sets) - classify the NEW message, not the "
    "earlier ones. Write question, topic and requested_change as "
    "standalone text that makes sense without the conversation."
)

# How many earlier turns the router sees - enough for a follow-up to
# resolve "it"/"that", not so many that old topics bleed into new ones.
_HISTORY_TURNS = 6


class ChatRouteDecision(pydantic.BaseModel):
    tool: ChatTool
    field_id: int | None = pydantic.Field(
        default=None,
        description="The WeeklyPrescription id this message is about, if any. "
        "Leave null if the message didn't already tell you one.",
    )
    target_field: Literal["sets", "reps", "load", "rir"] | None = pydantic.Field(
        default=None,
        description="For adjust_prescription only: which value the user "
        "wants changed - 'sets', 'reps', 'load' (%1RM) or 'rir' (effort).",
    )
    adjustment_kind: Literal["set_value", "increase", "decrease", "regenerate"] | None = pydantic.Field(
        default=None,
        description="For adjust_prescription only: an exact value, a direction, "
        "or a plain regenerate.",
    )
    requested_value: str | None = pydantic.Field(
        default=None,
        description="For adjust_prescription with adjustment_kind='set_value' "
        "only: the exact value the user asked for, e.g. '4' or '75% 1RM'.",
    )
    requested_change: str | None = pydantic.Field(
        default=None,
        description="For adjust_prescription only: the user's request, "
        "verbatim or summarized.",
    )
    question: str | None = pydantic.Field(
        default=None,
        description="For discuss_prescription only: the user's question, "
        "verbatim or summarized.",
    )
    topic: str | None = pydantic.Field(
        default=None,
        description="For answer_general_question only: the research topic "
        "being asked about, phrased as a clear question.",
    )


def route_chat_message(
    message: str, known_field_id: int | None = None, history: list | None = None
) -> ChatRouteDecision:
    context = (
        f"This message is already anchored to WeeklyPrescription id "
        f"{known_field_id} - do not report a different field_id."
        if known_field_id is not None
        else "This message is not anchored to any specific field."
    )
    # Passed as a labeled transcript inside one user message rather than as
    # real prior chat turns, so the model reads it as reference material
    # rather than as its own earlier outputs to continue from.
    recent = (history or [])[-_HISTORY_TURNS:]
    transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in recent)
    conversation = f"Earlier conversation (for resolving references only):\n{transcript}\n\n" if transcript else ""
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\n\n{conversation}New message: {message}"},
        ],
        response_format=ChatRouteDecision,
    )
    message_out = completion.choices[0].message
    if message_out.refusal:
        raise ValueError(f"Router refused to classify: {message_out.refusal}")

    decision = message_out.parsed
    if known_field_id is not None:
        # Structural context is trusted for WHICH field this is about; the
        # model's own field_id guess never is, even though the tool
        # selection itself still is (phase6_chat_routing_concepts.txt
        # section 3) - this is the field_id half of that split.
        decision.field_id = known_field_id
    return decision
