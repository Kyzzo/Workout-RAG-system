# Design Decision: Shared Research Answers

Verifying every number with a strong judge model made programs accurate —
and expensive. Generating one six-day program cost an estimated ~590 calls
to the large model. This document covers how that came down to about 29
for the first program of a given setup and zero for every one after it,
without weakening verification at all.

## Where the cost actually was

Counting the calls one program made showed the cost wasn't spread evenly:

| Step | Asked per | Share of calls |
|---|---|---|
| Reps and effort (reps in reserve) | exercise (~50–60 per program) | ~75% |
| Weekly volume | muscle (14) | ~12% |
| Frequency | muscle (14) | ~12% |

The per-exercise questions were the obvious target, and the generated
values made the case: bench press, squat and lateral raise all came back
"8–12 reps" for hypertrophy, with effort at "1–2 reps in reserve" nearly
everywhere. ~100 calls were producing a handful of distinct answers.

## The question is the same, so ask it once

The research behind these values isn't exercise-specific. The
repetition-range and proximity-to-failure studies don't study bench press
versus lateral raises; the volume and frequency meta-analyses pool
muscles. So the questions were restated at the level the research
actually answers them:

- **Reps, effort and load** are asked per *movement type* (compound or
  isolation) and training goal. Load is the one distinction the research
  does draw — lighter loads need sets closer to failure — and movement type
  stands in for it. Exercise selection already classified each exercise as
  compound or isolation; that's now stored.
- **Weekly volume, frequency and progression** are asked once per training
  goal (plus volume preference for volume), not once per muscle. Each
  muscle still gets its own record, citations included.

The measured effect of each step:

| Version | Large-model calls, first program | Time |
|---|---|---|
| Per exercise, per muscle | ~590 (estimated) | — |
| Per movement type, per muscle | 151 (measured) | 5.5 min |
| Per movement type, per goal | 29 (measured) | 2 min |

## Then store the answer for everyone

Once the questions stopped mentioning a specific exercise or muscle, two
programs with the same goal and volume preference ask *exactly* the same
questions against the same evidence. So each verified answer — value,
citations and every verdict — is stored once in a shared table and reused.
The second program with the same setup makes no calls to the large model
at all and finishes in about 20 seconds. There are only six goal-and-
preference combinations, so after a small one-time warm-up, nearly every
program costs well under a cent (the remaining cost is a small model
picking exercises).

## The rules that keep shared answers honest

Reuse is only safe if a stored answer is as trustworthy as a fresh one:

- **Only verified answers are stored.** An answer the judge couldn't
  support is regenerated on every request rather than cached, so an
  unlucky draw never becomes everyone's answer.
- **Stored answers are judged twice.** Each cited excerpt gets two judge
  verdicts and keeps the weaker one (see the
  [verification pipeline](citation-verification-pipeline.md#verified-once-judged-twice)).
  The cost is paid once per answer, not per program.
- **They expire when their inputs change.** The storage key includes a
  version string bumped whenever a generation or judge prompt, model or
  reasoning setting changes, so older answers simply stop being found.
  After new papers are ingested, the table is cleared so answers are
  regenerated against the new evidence.
- **Personal edits stay out of it.** A user asking chat to change one
  exercise's value still asks about that exercise and isn't cached — the
  shared layer holds research answers, not a user's choices.
- **They're reviewable.** Because one answer now applies to everyone, a
  script lists every stored answer with its supporting papers, and any one
  can be cleared to regenerate it.

Parallel requests for the same question (a block generates many exercises
at once) wait on a per-question lock instead of all generating it, with a
database uniqueness constraint as the backstop across processes.

## Trade-offs

- **One draw applies to everyone.** Model answers vary run to run within
  what the research supports; one run stored "0–1 reps in reserve" for
  compound hypertrophy work, another "1–2". Both were verified, but
  whichever is stored is what every program gets until it's cleared. That's
  why review and double judging matter more here than they would for a
  per-program answer.
- **Coarser questions.** Asking per goal rather than per muscle gives up
  muscle-specific answers. In practice they barely differed (moderate
  volume came out 12 weekly sets for 12 of 14 muscles), and the few
  muscle-specific findings in the corpus still appear as supporting
  excerpts. If the corpus grows real muscle-specific dosing research, the
  question can be keyed per muscle again for those muscles.
- **Personalization has to stay outside.** Anything that should differ per
  person (training experience, injuries) can't live in a shared answer;
  it has to be layered on top, the way chat edits already are.

## Alternatives considered

- **A cheaper judge for generated values** — tested with the regression
  check and rejected: it accepted the core misrepresentation ("31 sets as
  a dose") on every run.
- **Fewer judge checks per value** (stop after two confirmations) — would
  save calls but show fewer sources; unnecessary once sharing removed most
  of the cost.
- **Switching providers** — doesn't change the economics on its own (the
  calls cost money either way) and would mean re-tuning every prompt.
