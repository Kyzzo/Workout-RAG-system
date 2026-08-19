# Design Decision: Citation Verification Pipeline

Field-level attribution ([design doc](field-level-citation-attribution.md))
establishes *what* per-parameter citation is and why this product needs
it. It leaves one problem open: a self-reported citation is a claim, not a
fact. A model can hallucinate a plausible-looking source, or genuinely
misattribute a value to a source that didn't actually determine it. This
document covers the shape of how that claim gets checked against reality —
at a level of detail meant to explain the reasoning, not to serve as an
implementation spec.

## Self-report, but not a binary claim

Each generated value self-reports its own source(s) and an honest signal
about how confidently grounded it actually is — a model blending retrieved
content with its own background knowledge is the realistic default, not
an edge case, so forcing a strict grounded/not-grounded flag forces a
false choice the model can't honestly make. There's an explicit escape
hatch for "nothing retrieved actually supports this" rather than forcing
the model to fabricate a citation just to fill a field.

**The throughline principle for this whole design:** a false "not
grounded" (the system underclaims when real support existed) is a much
safer failure than a false "grounded" (the system claims support that
isn't real) — the former just underdelivers, the latter actively lies.
Every asymmetric choice in this pipeline traces back to biasing toward the
first kind of failure over the second, rather than treating both errors
as equally bad.

## Structural prevention of outright fabrication

Rather than trusting a free-text citation reference the model could
invent, the set of things a model is even *allowed* to cite is
constrained at generation time to what was actually retrieved for that
specific request. This makes pure fabrication structurally impossible
rather than something to detect after the fact — the model literally
cannot express a source that was never retrieved, because the schema it's
generating against doesn't include one. It doesn't verify that a selected,
real source is the *true* cause of the value — only that it's a real
candidate.

## A cheap check that can only confirm, never deny

A fast, low-cost check looks for a directly stated match between a cited
source and the generated value. The important design rule: **this cheap
check may only ever confirm a citation, never deny one.** A value can
legitimately fail a strict match against one cited source while still
being a valid, reasoned synthesis across multiple sources — a model might
adjust a number based on context drawn from a second citation whose own
content doesn't literally state the final value. A simple check can't
reliably tell "this citation is false" apart from "this citation is real
but the model reasoned beyond it." So a confident, clean match resolves
immediately; anything less than that escalates to a more capable check
rather than being auto-rejected. This makes the cheap layer an
*accept-only* filter — fast and free for the common case, but never the
one to render a negative verdict.

## Escalation to a more capable, narrowly scoped check

Cases the cheap check can't cleanly resolve go to a second pass — still
narrowly scoped to one question (does this specific source actually
support this specific value), not an open-ended re-derivation of the
whole answer. This is a reasoning task, not a simple matching task, which
is what's needed once the cheap layer runs out of confidence.

The outcome distinguishes more than a simple yes/no: a citation can
directly and substantially support a value, or it can plausibly have
informed the value without being its literal source, or it can bear no
real relationship to the value at all — and these get treated and
displayed differently. Collapsing that middle case into a flat rejection
would silently discard genuinely relevant citations; collapsing it into a
flat acceptance would overstate how directly a source supports a number.
Getting a model to make that finer distinction reliably requires giving it
concrete criteria for the distinction, not just a wider set of labels to
choose from — left unguided, a model tends to collapse back toward a
binary judgment.

This second pass is deliberately not run on every citation unconditionally
— only on what the cheap layer couldn't resolve, since an unconditional
second pass on every generated value across a whole program's worth of
fields would compound real cost.

## Why the boundary between the two tiers sits where it does

The two tiers have genuinely different cost/accuracy profiles, and the
split is deliberate. The cheap check is nearly free but narrow — its only
possible error, restricted to accept-only, is being overly cautious
(escalating something that could have been safely auto-accepted) — a pure
cost inefficiency, never a wrong final verdict, since it isn't allowed to
render one in the negative direction. The scoped second-pass check costs
real money and latency per use, but has a materially higher accuracy
ceiling — it's the only layer able to reason about synthesis across
sources rather than just simple matching. It's still not infallible, and
its own small error rate is accepted deliberately rather than chased to
zero, which has diminishing returns past a certain point of prompt
scoping and consistency.

The same asymmetry that motivates the whole design applies at both tiers:
never let the cheap check deny support on its own, because a wrong cheap
rejection would hide a citation with zero opportunity for review — the
most silent, hardest-to-catch version of the bad failure mode. Keeping the
escalation trigger inclusive (anything not cleanly confirmed escalates)
follows the same logic — under-escalating to save cost risks real blind
spots going unchecked, while over-escalating only costs money and
latency, a bounded, recoverable problem.

## Multiple citations per value: verify independently, don't average

A single generated value can cite more than one source. Each is verified
independently — never collapsed into one aggregate verdict for the whole
set. A source that turns out unsupported has to surface as a problem
regardless of how many others support the value; a supporting citation
should never be allowed to mask a contradicting one riding alongside it.
This also reflects a real product stance: sports-science research
genuinely disagrees on some of these variables, and showing that
disagreement (rather than quietly averaging it away) is more honest than
forcing one collapsed verdict across sources that are playing different
roles in the answer.

## What happens with a verdict

Verified citations are surfaced to the user, but not all identically — a
direct match reads differently than "this plausibly informed the
reasoning." Citations that fail verification are retained internally
(useful for understanding failure patterns over time) but never displayed
as if they were valid — if a value's only citation ends up unsupported,
the value's displayed grounding reverts to effectively uncited rather than
showing a false citation as though it were trustworthy.

When a value can't be substantiated even after a single bounded retry (not
an unlimited loop — repeating an identical query against an unchanged
corpus has no structural reason to produce a different result if the
underlying cause isn't noise), the generated value is still shown to the
user — never withheld — consistent with a "best estimate over outright
refusal" philosophy applied elsewhere in generation. What's missing is
grounding, not an answer, and the two aren't conflated: an honest,
upfront "this is a general estimate, not tied to a specific study" reads
differently to the user than a claim of grounding that actively failed
verification.

## Alternatives considered and rejected

- **Exact literal matching between a value and its source text** —
  rejected outright. Dosing literature is dominantly range-based, not
  point-value-based, so literal matching would flag the majority of
  legitimate cases as unsupported.
- **Embedding similarity as the primary verification signal** — rejected.
  Content drawn from the same narrow domain compresses into a similar
  similarity range regardless of true causal support, so a genuinely
  correct citation can score only moderately while an unrelated-but-
  similar-sounding source scores comparably. Kept only as a cheap,
  passively logged signal for possible future calibration, never as
  product-facing logic on its own.
- **Letting the cheap check assign a rejection directly** — an earlier
  version of this design did this, and it was reversed once the
  "plausibly informed, not the literal source" middle case was identified:
  it would silently discard citations that genuinely contributed to an
  answer through reasoning rather than direct matching, which is a worse
  failure than the extra cost of always escalating ambiguous cases
  instead.

## Known limits

The honest one, stated directly rather than glossed over: this pipeline
verifies **consistency**, not **causation**. Every check here can confirm
"this value is consistent with what this source states" — none can prove
the source actually *caused* the model to produce that value. A model
could in principle generate a value from its own training first, then
select a citation from among several retrieved candidates that happens to
be numerically consistent with it, and every check here would pass. This
design reduces the frequency of that failure; it doesn't structurally
eliminate it, because nothing here has real access to the generating
model's internal process — only to plausibility after the fact.

Relatedly, when a value is genuinely part retrieved content and part the
model's own background knowledge, no mechanism here can cleanly decompose
"how much came from where" — that's not a gap specific to this design,
it's an unsolved problem for grounded-generation systems generally. The
self-reported confidence signal and the finer-grained verification outcome
are honest signals about this blending, not a solved decomposition of it.
