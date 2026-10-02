# Design Decision: Routing a Chat Interface to the Right Mode

This started as an early design sketch that fell out directly from
designing the [citation verification pipeline](citation-verification-pipeline.md)
and the [three-mode framing](field-level-citation-attribution.md#three-modes-not-two)
it settled on. It has since been built; the design below held up largely
as sketched, and [what building it changed](#what-building-it-changed) is
covered at the end.

## The three modes a chat message could need

1. **Field-level generation or editing** — "change my squat reps to 4-6."
   Routes into the full citation verification pipeline unchanged.
2. **Field-level discussion** — "why is this 5-8 reps." No new generation
   or verification needed — surfaces an already-stored verdict.
3. **General-knowledge Q&A** — "what does research say about training to
   failure." Response-level citation, not tied to any specific persisted
   value.

The interesting problem: given a free-text message, how does the
application know which of these three a given message actually is?

## Routing: structural context first, model choice second

Two complementary mechanisms, layered — preferring a constrained,
structural answer over an inferred one wherever possible, the same
instinct behind constraining citation IDs to an enum rather than trusting
free text.

**Structural context, when available, needs no inference at all.** If a
chat thread is opened *from* a specific field (a "why is this 5-8 reps"
affordance attached to an actual generated value in the UI), which field
is being discussed is already known from where the conversation started —
zero ambiguity, no classification step required. This should be the
majority path if the interface is built to encourage opening a
conversation from a specific number rather than only from a generic,
unanchored entry point.

**Structured tool selection, for a general or unanchored entry point.**
Rather than a separate "classify this message" call, the model is given a
fixed menu of callable actions and its selection among them *is* the
routing decision — something like `adjust_prescription(field_id,
requested_change)`, `discuss_prescription(field_id, question)`, and
`answer_general_question(topic)`. The model must choose from this fixed
set — it can't invent a fourth, undefined behavior — and whatever
arguments it fills in for the chosen action are still schema-validated,
the same trust-but-verify posture as every other structured generation
call in this system. This is a materially more constrained decision than
open-ended generation, but it's still a judgment call, not a guarantee —
picking the wrong action for a given message is a real, accepted residual
risk, the same category as any verification model's own error rate, just
bounded to a fixed, inspectable set of outcomes instead of arbitrary free
text.

## Ownership still has to be checked, not just intent

Selecting an action correctly is necessary but not sufficient — the
resource being acted on still has to belong to the requesting user. Both
the editing and discussion actions take a field identifier the model
supplies (or that comes from anchored context), and that identifier needs
independent re-verification against the requesting user's own ownership
chain before anything happens with it — never trusted just because a
model chose to act on it, or because the interface happened to anchor a
conversation to it.

This isn't a new mechanism to invent for this feature specifically — it's
the same ownership-scoping pattern already built and deliberately tested
elsewhere: walk the resource's parent chain up to its owning user and
confirm it resolves to the requester, rejecting rather than trusting a
mismatch. A chat-based entry point is a genuinely new way into the system,
and a model-supplied or context-supplied identifier is a different code
path than a URL parameter — it would be a real, silent gap if an existing
ownership check were only ever re-implemented for direct API routes and
not for whatever handles a chat-originated action.

## What each route does with citations

The editing path uses the full field-level verification pipeline
unchanged. The discussion path costs nothing extra in verification terms
at all — it reads and displays an already-computed, already-verified
result rather than re-running anything. The general-question path uses
response-level citation, reusing only the cheap, universal part of the
field-level design (constraining citable IDs to what was actually
retrieved, since preventing fabricated citations is worth doing
regardless of citation granularity) without the field-specific numeric
verification, since there's no single persisted value to check a claim
against.

## What building it changed

The routing layer and the ownership rule went in as designed: anchored
context sets the field identifier outright and overrides anything the
model reports, and every action that touches a stored value goes through
one shared ownership check that the direct API routes also use, rather
than a second copy written for chat. Negative-path tests call each chat
action as a different user and assert it's rejected.

Two parts of the sketch turned out to be too simple once they ran against
real input:

- **"Discussion costs nothing" was only half true.** The first version of
  the discussion path returned the stored value and its citations as-is,
  with no regard for what the user had actually asked. That's cheap, but
  it doesn't answer the question. The fix keeps the *verification* cost at
  zero (nothing is re-retrieved or re-checked; only already-verified,
  supporting citations are read) while adding one model call that answers
  the question asked, restricted to the stored value and those citations.
- **Response-level citation needed to be claim-level to be honest.** The
  first general-question version attached a flat list of cited sources to
  the whole answer and verified each one against the whole answer. Real
  testing produced a genuine misattribution: an excerpt reporting what
  share of studies in a dataset used a particular method got cited as
  support for a claim that the method *works better* — a real source, a
  real retrieval, backing a claim it never made. The fix: each citation now
  names the specific claim in the answer it's cited for, and verification
  judges the source against that one claim rather than the answer as a
  whole. Citations that fail are dropped from what's shown, with the same
  single bounded retry and caveat messages used everywhere else in
  generation.

## Genuinely open questions

- What happens when a message gets routed to the wrong action — still no
  detection or recovery mechanism.
- Conversation state. Each message is currently routed and answered on its
  own, with no conversation history, so a discussion can't carry context
  into a follow-up edit request yet.
- Edits beyond numbers. Representing an in-place exercise swap without
  rewriting already-cited history is still an open schema question (see
  [future work](../future-work.md)).

## Edits that do what was asked

The first version of the edit action identified which value to change and
then simply regenerated it, ignoring the request itself. Edits now come in
three structured kinds, extracted by the same routing call:

- **A direction** ("more volume", "go lighter"). Generation is told the
  current value and the direction, and to leave the value unchanged if the
  research doesn't support moving that way. The result is then checked
  mechanically: if the value didn't move, or moved the wrong way, nothing is
  saved and the user is told why. The check only compares like with like —
  a load expressed as a percentage of a max can be compared with another
  percentage, but not with an effort rating, so a change across units is
  accepted as a change rather than judged higher or lower.
- **An exact value** ("make it 4 sets"). This is an informed override, the
  case field-level attribution exists to support. The value field's type is
  constrained to exactly the requested value, so the model can't quietly
  substitute its own number — all it can still decide is which retrieved
  sources genuinely support that value. Verification then checks those
  claims exactly as it would for a generated value. If nothing supports it,
  the value is still applied, with a caveat that says it was the user's
  choice rather than a generic "not substantiated" message — the user
  overruled the research knowingly, and the record should say so.
- **A plain regenerate** ("update this based on the latest research"),
  which behaves as before.
