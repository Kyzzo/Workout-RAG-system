# Accuracy Hardening: From "Mostly Right" to Checkable

This log covers the stretch of work that started with one wrong chat
answer and ended with a different judge, a different retrieval pipeline,
a regression harness and an ~95% cost cut. The design documents describe
where things landed
([verification](../design-decisions/citation-verification-pipeline.md),
[retrieval](../design-decisions/retrieval-and-reranking.md),
[shared answers](../design-decisions/shared-research-answers.md),
[program options](../design-decisions/research-bounded-program-options.md));
this is how it got there, including what turned out to be wrong along the
way.

## The trigger: a true-sounding false answer

Asked what the most effective weekly set range is for hypertrophy, the
chat answered "18 to 31 sets per week is optimal." Both numbers came from
real, retrieved, cited sources:

- one meta-analysis found "no detectable superiority beyond ~31
  *fractional* sets per week" — a limit of what the data could show, in a
  unit that counts indirect work as half a set;
- another study found 12, 18 and 24 weekly sets produced *similar* growth
  in trained lifters, and that ~18 sets may optimize *squat strength*.

The answer merged a boundary of the data with a strength finding into a
hypertrophy optimum neither source states. For a product whose premise is
that every claim can be checked against a source, that's the worst kind
of failure: correct citations attached to an incorrect claim.

## Statement-level verification for chat

Chat answers had been verified as a whole against their sources. They're
now generated as individual statements, each naming its sources, and every
statement–source pair is judged on its own; a statement survives only if
a source supports it *as written*. Unsupported or uncited statements are
dropped and the answer says how many. If nothing survives, the user is told
plainly that the corpus doesn't support a confident answer — there's no
fallback to unverified prose.

That made answers accurate and, it turned out, unreadable: lists of
near-quotes. A user wants a rough range the research generally supports.
Two causes, found by tracing rather than guessing:

- **Retrieval, not verification.** The judge hadn't removed anything. The
  five retrieved excerpts were three from a rep-range paper (the word
  "range" in the question), a reference list and one relevant study — the
  volume meta-analyses never reached the model. (This started the
  retrieval work below.)
- **The rules forbade synthesis.** One claim per excerpt makes "most
  research supports roughly 10–20 sets" impossible to say.

Answers now open with a short summary that may synthesize across sources,
judged against all of them together for being a fair consensus — rough,
hedged ranges pass; a narrowed "optimal" sub-range, a data boundary read as
a ceiling, or mixed units still fail. The evidence statements follow,
folded under "Show the evidence".

## The judge was the weak link — measured, not assumed

The original small judge model was tested against the known cases. Five
cases (three real misrepresentations, two faithful claims):

| Judge | Correct of 5 | Note |
|---|---|---|
| small model (original) | 2 | accepted all three misrepresentations |
| mid-size models | 3–4 | missed the hedged "may be an upper limit" |
| strongest model, full reasoning | 5 | ~17 s per check |
| strongest model, low reasoning | 4 | ~5 s per check |

Prose claims now go to the strongest judge at full reasoning; generated
numbers to the same model at low reasoning. One plan — a mid-size model
for generated values — died on an operational detail: its rate limit on
this account was 30,000 tokens per minute, so a program's parallel checks
came back as errors, which the pipeline correctly counts as "unverified".

## Bugs that only showed up in real runs

- **An accept-only shortcut that accepted wrongly.** A cheap numeric check
  approved citations without the judge if the excerpt contained a sets
  range covering the value. It approved 18 weekly quad sets for
  hypertrophy because the excerpt said "12–24" — in a passage whose 18 was
  a strength finding. The judge rejected the same citation. The shortcut
  was removed; "accept-only" only guarded the direction that wasn't
  dangerous.
- **A question that made correct answers fail.** With the shortcut gone,
  the judge rejected nearly every volume citation — because the question
  asked for the *optimal* volume, and dose-response research never names
  one. Reworded to "what the research supports as effective", in the app's
  own unit, correct values verified again.
- **"Moderate" aiming for the data's edge.** Unguided, the generator picked
  31 weekly sets — the no-detectable-superiority point — as a target.
  Guidance fixed it at first; binding options to the meta-analysis's
  efficiency tiers fixed it structurally.
- **A garbled paper.** One PDF's extracted text had lost every space
  ("Resistancetraining(RT)outcomes…"), which made its excerpts look
  irrelevant in the sources panel. The loader now detects pages where
  words have merged and re-extracts them in a layout-preserving mode —
  only those pages, since that mode interleaves two-column layouts.
- **Tests that quietly called the real model.** After generation moved to
  movement-type questions, two tests stopped intercepting the model calls
  and silently made real paid calls. Unit tests now fail immediately on any
  unmocked model call.

## A regression harness for judgment

The unit tests mock every model call, so they prove the app's logic but
say nothing about whether the judge judges well. A separate check replays
each known misrepresentation and its faithful counterpart against fixed
excerpts copied from the corpus (so retrieval changes can't move the
target), plus live generation cases, several runs each, reporting pass /
flaky / fail and keeping API errors separate from accuracy failures. It's
the gate for prompt and model changes. It was immediately useful: it's how
a cheaper judge for generated values was rejected (it accepted "31 sets as
a dose" on every run), and how one borderline case was identified as
genuinely ambiguous rather than broken.

## Then the bill

Accurate generation with a strong judge on every number cost an estimated
~590 large-model calls per program. Most of that was the same research
question asked per exercise and per muscle. Asking it at the level the
research answers it, and storing each verified answer for reuse, brought a
first program to 29 calls and every later one with the same setup to zero —
see [shared research answers](../design-decisions/shared-research-answers.md).
Because one stored answer now serves everyone, it's judged twice before
it's stored.

## Retrieval, measured

Several "verification" problems were really retrieval problems, so
retrieval got its own check: expected papers per question, reported as
recall. Reranking candidates by how well they answer the question (rather
than how similar their wording is), plus pulling a few candidates from
every paper, took it to 23 of 23 — after the check itself caught a
reranker that silently scored only 3 of 40 candidates, and a model too weak
to recognize a statistical result as an answer. Details in the
[retrieval design doc](../design-decisions/retrieval-and-reranking.md).

## What this taught

- Correct citations don't make a correct claim. Verification has to judge
  the claim as written — units, outcomes, populations and the strength of
  a finding — not the presence of a matching number.
- "Accept-only" isn't automatically safe; it depends on which error is
  dangerous.
- How a question is worded decides what a verifier will accept.
- When an answer looks wrong, trace the pipeline before tuning the prompt:
  most of the time here, the model never saw the right evidence.
- Every model choice was made by measuring candidates on real failure
  cases, and the measurements are kept as a harness so the next change is
  measured the same way.
