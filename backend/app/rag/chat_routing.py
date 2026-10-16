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
ChatTool = Literal["adjust_prescription", "discuss_prescription", "answer_general_question", "conversation"]

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
    "increase it) or 'exercise' (swap/replace the exercise itself - put "
    "the exercise they name in requested_value, or leave it null if they "
    "want one suggested) the "
    "request is actually about, and adjustment_kind to what's being asked: "
    "'set_value' if the user names an exact value (also put that value in "
    "requested_value, e.g. '4' for sets or '75% 1RM' / 'RPE 8' for load), "
    "'increase' or 'decrease' for a direction without an exact value "
    "('more volume', 'go lighter'), or 'regenerate' to just redo it from the "
    "research ('update based on the latest research').\n"
    "- discuss_prescription: the user is asking ABOUT a specific already-"
    "generated value in their program without asking to change it, e.g. "
    "'why is this 8-10 reps' or 'what's the evidence behind this'. If they "
    "ask why this exercise was chosen rather than about one of its values "
    "('why this exercise?', 'why was this picked?', 'is there a better "
    "exercise for this muscle?'), set target_field to "
    "'exercise' (a request to replace it is adjust_prescription). Only when "
    "the message is anchored to a field: a follow-up about an earlier "
    "answer in this conversation (e.g. 'what is that in ordinary sets?') is "
    "answer_general_question.\n"
    "- answer_general_question: a free-standing research question not "
    "about one specific prescribed value, e.g. 'what does research say "
    "about training to failure'.\n"
    "- conversation: the message isn't a request at all - thanks, a "
    "greeting, a reaction or complaint about an earlier answer ('that's "
    "wrong', 'what the hell', 'huh?'), or something unclear or off-topic. "
    "Set conversation_kind. Never use it for a message that asks a "
    "training question or for a change, however casual or rude: 'wtf, so "
    "how many sets for chest?' is a question, and so is a question about "
    "pain or injury.\n"
    "If the message is anchored to an exercise (you'll be told which, and "
    "its current values), the anchor is context, not necessarily the "
    "subject:\n"
    "- A request to change one of its values or swap it is "
    "adjust_prescription.\n"
    "- discuss_prescription is ONLY for a question about this exercise's "
    "own sets, reps, load or effort (RIR) - why they are what they are, "
    "whether they suit the user, the evidence behind them ('why 2 sets?', "
    "'is 0-1 RIR too hard for me?', 'should I go heavier on this?') - or "
    "about why this exercise was chosen or whether another exercise would "
    "be better for the muscle (target_field 'exercise').\n"
    "- Anything else is answer_general_question, even when it says 'this' "
    "or names the exercise: rest between sets, rep speed or tempo, exercise "
    "order, warm-ups, technique, pain or injury, deloads, how often to "
    "train a muscle, and what the best, optimal or recommended amount is in "
    "general ('how many sets should I do for chest'). Write its topic as a "
    "standalone question that names the exercise when it matters.\n"
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
    target_field: Literal["sets", "reps", "load", "rir", "exercise"] | None = pydantic.Field(
        default=None,
        description="For adjust_prescription: which value the user wants "
        "changed - 'sets', 'reps', 'load' (%1RM), 'rir' (effort), or "
        "'exercise' to swap the exercise for another. For "
        "discuss_prescription: the value the question is about ('sets', "
        "'reps', 'load' or 'rir'; null if it is about all of them), or "
        "'exercise' only when the question is about the choice of exercise "
        "itself rather than any of its values.",
    )
    adjustment_kind: Literal["set_value", "increase", "decrease", "regenerate"] | None = pydantic.Field(
        default=None,
        description="For adjust_prescription only: an exact value, a direction, "
        "or a plain regenerate.",
    )
    requested_value: str | None = pydantic.Field(
        default=None,
        description="For adjust_prescription with adjustment_kind='set_value' "
        "only: the exact value the user asked for, e.g. '4' or '75% 1RM'; for "
        "target_field='exercise', the exercise they want instead (null to "
        "have one suggested).",
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
    conversation_kind: Literal["thanks", "complaint", "greeting", "unclear"] | None = pydantic.Field(
        default=None,
        description="For conversation only: what kind of message it is.",
    )


def route_chat_message(
    message: str, known_field_id: int | None = None, history: list | None = None, anchor: str | None = None,
) -> ChatRouteDecision:
    """`anchor`: the anchored exercise and its current values, so the router
    can tell a question about them from one that only mentions the
    exercise ('how long should I rest between sets of this?')."""
    context = (
        f"This message is already anchored to WeeklyPrescription id "
        f"{known_field_id} - do not report a different field_id."
        + (f" It is {anchor}." if anchor else "")
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
