# Design Decision: Citation Verification Pipeline

Field-level attribution ([design doc](field-level-citation-attribution.md))
establishes *what* per-parameter citation is and why this product needs
it. It leaves one problem open: a self-reported citation is a claim, not a
fact. A model can hallucinate a plausible-looking source, or genuinely
misattribute a value to a source that didn't actually determine it. This
document covers how that claim gets checked against reality — at a level
of detail meant to explain the reasoning, not to serve as an
implementation spec. The [accuracy hardening log](../engineering-log/accuracy-hardening.md)
covers the incidents and measurements that shaped the current version.

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
first kind of failure over the second.

## Structural prevention of outright fabrication

Rather than trusting a free-text citation reference the model could
invent, the set of things a model is even *allowed* to cite is
constrained at generation time to what was actually retrieved for that
specific request. Pure fabrication is structurally impossible rather than
something to detect after the fact — the schema the model generates
against has no way to express a source that was never retrieved. It
doesn't verify that a real source is the *true* support for the value —
only that it's a real candidate. That's the judge's job.

## Every citation goes to a judge

Each cited source is checked by a separate model call scoped to one
question: does this specific excerpt support this specific value (or
sentence) *as written*? The outcome distinguishes three cases — the
excerpt states or directly covers the value, the excerpt reports findings
that plausibly informed it without stating it, or it doesn't support it —
and they're displayed differently. Collapsing the middle case into a
rejection would discard genuinely relevant evidence; collapsing it into
acceptance would overstate how directly a source backs a number. Getting a
model to make that finer distinction reliably required concrete criteria
in the prompt, not just three labels.

An earlier version put a cheap, accept-only numeric check in front of the
judge: if an excerpt contained a sets range covering the value, the
citation was accepted without a model call. It was removed. "Accept-only"
was meant to make it safe — it could never wrongly *reject* — but it could
wrongly *accept*, and that's the dangerous direction. In practice it
approved 18 weekly quad sets for hypertrophy from a study whose
"approximately 18 sets" was a *strength* finding, because the same excerpt
also mentioned "12–24 sets" — while the judge, asked the same question,
rejected the citation for exactly that reason. A number inside a range
says nothing about whether the range is for the same outcome, unit or
population.

## What the judge checks: qualifiers, not just numbers

The failure that prompted the current rules was a chat answer that called
one meta-analysis's "no detectable superiority beyond ~31 *fractional*
sets" and another study's "12–24 sets produced similar growth" an "18 to
31 sets optimal" range. Every number in that sentence came from a real
source; the sentence was still false. So the judge rejects a claim that
changes any of:

- **the unit** — fractional sets (indirect work counted as half) presented
  as direct sets, or sets per session presented as sets per week;
- **the outcome** — a strength finding presented as a hypertrophy finding;
- **the population or muscle** studied, generalized without saying so;
- **the strength of the finding** — "no detectable superiority beyond X"
  read as a ceiling or as a dose to aim for, "similar outcomes across A–B"
  read as part of that range being optimal, "a trend" read as an effect;
- **the figures themselves** — merged from different sources into a new
  range, or narrowed (18–24 where the source said 12–24).

Introductions, methods sections and reference lists that report no
results of their own are not support of any kind, however closely their
topic matches.

## What a generated value claims

A generated number is a point chosen from what the research supports, not
a claim that it's the single best value. That distinction turned out to
matter in both directions. When the question behind a value asked for the
"optimal" weekly volume, the judge rejected almost every citation —
dose-response research reports effective ranges, efficiency tiers and
diminishing returns, never one optimum — so correct values went
unverified. Asked instead what volume the research supports as effective
(in the app's own unit, fractional sets), the judge accepts a value that
falls inside a range or tier the excerpt reports as effective for the
question's outcome, treats a value merely below a "no detectable
superiority" point as at most related evidence, and never accepts a figure
for a different outcome or unit.

## Choosing the judge by measurement

The judge model was chosen against known misrepresentations, not by
default. On a set of real cases (three misrepresentations from the
incidents above, two faithful claims), the original small model accepted
every misrepresentation. Larger models caught more; the strongest caught
all of them but took ~17 seconds per check. The current split follows the
cost and difficulty of each kind of claim:

- **Prose** (chat statements and summaries, the fixed claims behind
  mechanical rules) goes to the strongest judge at full reasoning effort.
  There are few per answer and they run in parallel.
- **Generated values** (bare numbers or short ranges) go to the same model
  at low reasoning effort, about 5 seconds per check. A cheaper model was
  tested for this role and rejected: it accepted "31 sets as a dose" on
  every run.

## Verified once, judged twice

Research answers are now shared across programs
([shared research answers](shared-research-answers.md)): the answer to
"what weekly volume does the research support for hypertrophy at moderate
volume" is generated, verified and stored once, then reused by everyone.
That raises the stakes on any one verdict — and the judge is not perfectly
consistent on borderline excerpts. So when a shared answer is created,
each cited excerpt is judged twice in parallel and the weaker verdict is
kept: an excerpt counts as support only if both passes agree. The extra
cost is paid once per answer, not per program. Edits a user makes to their
own program stay single-pass, since they aren't reused.

## Multiple citations per value: verify independently, don't average

A single generated value can cite more than one source. Each is verified
independently — never collapsed into one aggregate verdict. A source that
turns out unsupported has to surface as a problem regardless of how many
others support the value; a supporting citation should never mask a
contradicting one riding alongside it. This also reflects a product
stance: sports-science research genuinely disagrees on some of these
variables, and showing that disagreement is more honest than averaging it
away.

## What happens with a verdict

Verified citations are shown to the user, but not identically — "states
this directly" reads differently than "related evidence." Citations that
fail are retained internally (useful for understanding failure patterns)
but never displayed as if they were valid. If a value's citations all
fail, it gets one bounded retry (not a loop — repeating an identical query
against an unchanged corpus has no structural reason to produce a
different result if the cause isn't noise). If it still can't be
substantiated, the value is shown with an honest caveat rather than
withheld: what's missing is grounding, not an answer, and the two aren't
conflated. An unverified answer is never stored for reuse.

## Guarding against regressions

Prompts and models will keep changing, and nothing crashes when a judge
quietly starts accepting "18–31 sets is optimal" again. A regression check
replays every known misrepresentation (and the faithful version of each)
against fixed excerpts copied from the corpus, plus live generation cases,
several times each with real model calls, and reports pass / flaky / fail.
It runs before any judge or generation prompt or model change, and every
new misrepresentation found becomes a permanent case. It's separate from
the unit tests, which mock every model call and so can't say anything
about the judge's actual judgment.

## Alternatives considered and rejected

- **Exact literal matching between a value and its source text** —
  rejected outright. Dosing literature is range-based, so literal matching
  would flag most legitimate cases as unsupported.
- **Embedding similarity as the verification signal** — rejected. Content
  from one narrow domain compresses into a similar similarity range
  regardless of true support, so an unrelated-but-similar-sounding source
  scores about as well as a correct one.
- **A cheap accept-only range check in front of the judge** — adopted, then
  removed. It never wrongly rejected, but it wrongly accepted, skipping
  every qualifier check (see above).
- **A small, cheap judge everywhere** — rejected by measurement: it
  accepted every known misrepresentation.

## Known limits

The honest one: this pipeline verifies **consistency**, not **causation**.
Every check can confirm "this value is consistent with what this source
states"; none can prove the source *caused* the model to produce it. A
model could produce a value from its own training and then pick a
consistent-looking citation, and every check would pass. The design
reduces how often that happens; it can't eliminate it, because nothing
here sees the generating model's internal process.

The judge itself has a residual error rate and isn't perfectly consistent:
on genuinely borderline excerpts (for example, a passage about load ranges
cited for a rep range) the same verdict can flip between runs. Double
judging for shared answers and the regression check bound this; they don't
remove it.
