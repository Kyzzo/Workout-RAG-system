# Building Retrieval-Grounded Structured Generation

This covers the first real exercise of the project's core mechanism:
retrieval-grounded, structured generation for a single training variable
(weekly training volume), and the testing discipline used to prove it
actually worked rather than just appeared to.

## A retrieval-quality fix before writing the generation query

The exercise schema originally only tracked an exercise's name (e.g.
"Barbell Back Squat"). Sports-science volume research is framed around
*muscle groups* ("quadriceps"), not specific named exercises — a
retrieval query built from an exercise name alone matches the literature
more weakly than one built from the muscle group it actually trains. A
`muscle_group` field was added specifically to fix this before the
generation query was written, rather than accepting weaker retrieval and
working around it later.

This isn't a fully solved problem by itself, and it's worth being direct
about the remaining gaps: generating volume per exercise independently
means two exercises sharing a muscle group in the same week could each be
told the full research-backed range and collectively overshoot the real
weekly total for that muscle group — a generation-coherence problem that
belongs in later orchestration logic, not a retrieval fix. And an exercise
that trains multiple muscle groups at once (a deadlift trains back,
glutes, and hamstrings) makes "which muscle group's budget does this set
count against" genuinely ambiguous with a single muscle-group field. Both
are deliberately deferred rather than solved prematurely, since neither
blocks proving the core mechanism works for one exercise, one field, in
isolation.

## The retrieval → generation pipeline

1. A natural-language query is built from the muscle group and goal,
   phrased to semantically match how the literature actually discusses
   the topic ("What is the optimal weekly training volume for
   {muscle_group} to support a training goal of {goal}?") rather than a
   terse keyword string.
2. That query is embedded with the same embedding model used at ingestion
   time — this is what makes the similarity search meaningful at all; a
   different embedding space would make the comparison meaningless.
3. A category-filtered vector search retrieves the top candidate chunks,
   filtered to the relevant research category (e.g. "volume") before
   ranking by similarity — filtering narrows which points are eligible at
   all, a separate mechanism from the similarity ranking that runs after.
4. The retrieved text is joined into a context block and handed to the
   model alongside the question, using structured outputs so the response
   is validated against a schema rather than parsed from free text.
5. The model's refusal state is checked before trusting its parsed output
   — a real safety check, since structured-output calls can still refuse
   (for safety reasons, for example), and silently trusting an empty
   result would be a confusing failure mode later.

One deliberate prompt decision: the model is told to give its best
estimate from the provided context rather than refuse outright if the
context is thin. This keeps a small corpus from causing outright failures,
at the cost of a weakly-grounded answer not yet being distinguishable from
a strongly-grounded one at generation time — that distinction is exactly
what the citation verification layer built afterward is for.

## Scope: one field at a time, deliberately

The first generation target had exactly one field — weekly set count —
not reps as well, even though generating both is the real long-term goal.
The reason: at the time, the ingested corpus had literature specifically
about weekly *set* volume, not rep ranges. Generating a reps value with
nothing in the retrieved context to ground it would mean the model either
hallucinating a plausible number or falling back on its own training
knowledge — directly undermining the "grounded and auditable" premise
before the rest of the system around it even existed. Better to prove the
mechanism narrowly first than to generate an ungrounded field just because
the schema had room for it.

## Testing discipline: verify independently, not just plausibly

The core principle applied throughout: a function returning a
plausible-looking result is not the same as proof that it worked. A
generation call returning a set count proves the model call succeeded and
produced valid output — it does not by itself prove the retrieval found
genuinely relevant content (the model could have ignored weak context and
guessed), and a returned value does not by itself prove it was actually
persisted (a missing database commit produces an identical-looking return
value, right up until the process restarts and the change is gone).

The fix applied consistently: check the actual state independently of
what a function claims. For retrieval quality, that meant printing the
retrieved chunks and reading them, not just trusting a plausible output
number. For persistence, that meant querying the database directly with a
separate connection, not the same code path that might have the bug.

## Positive-path and negative-path testing

Testing that the correct thing happens for valid input is necessary but
not sufficient — testing that the wrong thing is correctly *prevented* is
just as important, especially for anything security-relevant. The
ownership check on generation requests only matters when someone tries
something they shouldn't be able to do; a test suite that only ever
exercises the correct-owner path would never actually catch a regression
in that check at all. After confirming the real owner could generate a
value successfully, the same call was deliberately repeated as a
*different* user's identity, asserting it fails rather than succeeds —
both directions checked, not just the one that's easy to remember.

## Testing at the right layer

A generation endpoint is a web route on the outside, but underneath the
routing decorator it's still a plain function — callable directly, without
going through HTTP or a running server, by importing it and calling it
with a real database session and a real user object. This is a legitimate
testing technique, not a shortcut that skips "real" testing: it isolates
the business logic (the query, the ownership check, the generation call,
the write-back) from the HTTP and auth plumbing around it, which had
already been verified separately. This is exactly what an automated
integration test does under the hood — it imports functions and calls
them directly, the same as this.

## Arrange, act, assert — even without a test framework

Every verification followed the same three-part shape any automated test
would, just typed out manually: seed known, controlled state first (a
specific exercise and a placeholder value deliberately set to something
obviously wrong, so seeing anything else afterward is itself meaningful);
perform the one operation being tested; then check the actual outcome
against what's expected — querying the database directly, comparing the
returned value, confirming the wrong user is rejected. This structure
carries forward unchanged once real automated tests are introduced later
in the project — formalizing it mostly means wrapping this same pattern in
assertions and a test runner, not inventing a new approach.
