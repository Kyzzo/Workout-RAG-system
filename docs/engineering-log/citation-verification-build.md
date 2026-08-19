# Building the Citation Verification Pipeline

This documents how the [citation verification design](../design-decisions/citation-verification-pipeline.md)
was actually implemented, and — the more interesting part — what testing
against real, messy corpus data caught that careful design-stage reasoning
alone hadn't anticipated. Specific prompts and matching logic are
described conceptually here rather than reproduced verbatim.

## Why the self-report schema has to be built dynamically per call

The set of sources a model is allowed to cite needs to be constrained to
exactly what was retrieved for *that specific request* — and that set is
different every call, since retrieval is a live search. A schema defined
once, ahead of time, can't express "valid values depend on runtime data,"
so the response format the model has to follow is constructed fresh for
every request, built from that call's actual retrieval results.

This is what makes the fabrication-prevention structural rather than a
validation step applied after the fact: the model literally cannot
express a source that wasn't retrieved, because the format it's
generating against doesn't include one. This was verified directly
against a real API call, not assumed from the schema compiling without
error — confirming every self-reported citation was genuinely a subset of
what had actually been retrieved for that request.

One prerequisite fix was needed first: the existing retrieval code
discarded the vector database's internal identifier for each result
entirely, keeping only plain text and a source label. That was fine while
nothing needed to reference a specific piece of retrieved content, but it
left nowhere to point a citation at once citations needed to reference one
specifically — fixed by preserving that identifier alongside each
retrieved piece of content.

## The cheap check: what a simple heuristic can and can't do

The fast, accept-only check looks for a directly stated numeric match
between a cited source and the generated value, and — per the design —
never rejects a citation on its own, only confirms one.

Testing this against real ingested corpus text, not hand-written examples,
surfaced a real, unanticipated problem: the document-extraction pipeline
produces text with inconsistent word spacing for a meaningful fraction of
content (dense body paragraphs specifically), while other content stays
normally formatted. The matching approach still worked reasonably well
despite this, because the specific pattern being matched survives even
when surrounding prose loses its spacing.

Testing against several real chunks pulled directly from the corpus also
caught a genuine false positive: content discussing a training concept in
general terms happened to sit right next to an unrelated numeric
reference (a citation index, not a dosing figure), and the two got
conflated by a heuristic that was, at that point, too permissive about
what counted as "nearby." The fix tightened the matching logic to
distinguish a genuine dosing statement from an unrelated number that
merely appears close to relevant-sounding language. Re-testing against
the same real chunks confirmed the false positive was gone with no
regressions elsewhere.

## The escalation check: a real precision gap, found and fixed

The more capable, narrowly-scoped verification pass was tested against
several real chunks chosen to each exercise a different part of its
intended behavior, not one easy case:

- Content stating several different numeric ranges for several different
  sub-categories — exactly the kind of case the cheap check had correctly
  declined to resolve, since it can't tell which of several stated ranges
  is the relevant one. The verification pass correctly picked out the one
  range that actually applied to the generated value and explained why —
  precisely the case this second layer exists for.
- Content that discusses a related concept in general terms without
  stating a specific number — classified as a legitimate contributing
  influence rather than a direct source, a defensible middle judgment
  rather than a forced binary.
- Content that is purely bibliographic — author names, titles, citation
  metadata, no actual findings or discussion. This one initially came back
  classified as a legitimate contributing influence rather than
  unsupported, which was a real precision problem: superficial topical
  relevance (a title that sounds related) isn't the same as content that
  could have actually informed an answer. Fixed by making the distinction
  between "discusses something relevant" and "contains no actual content
  at all" explicit rather than implicit. Re-testing confirmed the fix,
  with the model's own reasoning correctly identifying the excerpt as
  containing no real findings — while the other two classifications
  stayed correct and unchanged.

## Tying it together: self-reported confidence affects the fast path

The orchestration logic combines both layers with one deliberate rule: the
fast, cheap path to confirming a citation only fires when the model's own
self-reported confidence in that value is high to begin with — a
self-reported signal of partial or weak grounding forces the more capable
check even when a simple numeric match would otherwise have passed,
because the model's own admission of uncertainty casts doubt on the
citation regardless of surface-level agreement. The cheap check was never
verifying causation, only consistency — the model's own self-report is
the one signal that can flag when consistency isn't enough.

## End-to-end verification

The full pipeline — self-report, structural constraint, cheap check,
escalation, persistence — was tested against real retrieval, a real model
call, and a real database, not mocked components.

The test followed a deliberate arrange-act-assert shape: reset the target
value to an obviously-wrong placeholder first (so seeing anything else
afterward is itself evidence the write happened), call the generation
logic directly rather than through the HTTP layer (isolating the new logic
from request/auth handling that had already been verified separately), and
then check the result through a *separate* database connection rather than
trusting the function's own return value.

The result: several citation records were created for one generated
value, and they weren't all identical — most were confirmed, but one was
correctly flagged as unsupported. That mix matters — if every real run
only ever produced a confirmed result, that would be equally consistent
with "the pipeline works" and "the pipeline rubber-stamps everything." A
genuine unsupported verdict, produced by real reasoning against a real
self-reported citation, is evidence specifically for the former.

The existing ownership boundary (a user can only generate values for their
own program) was re-tested alongside the new write path and confirmed
still enforced correctly.
