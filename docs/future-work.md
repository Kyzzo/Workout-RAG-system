# Future Work and Known Limitations

Every deliberately-deferred design question in one place — decisions made
consciously, with reasoning for why they don't matter yet and what would
make them matter.

## Schema

**Reps and load are stored as strings, not structured numeric ranges.**
Real prescriptions are often ranges or non-numeric values ("8-10" reps,
"70% 1RM" or an RPE value for load) that don't cleanly fit a single
numeric column. Storing them as strings avoids forcing an early,
restrictive numeric schema before the generation and citation logic had
proven out what shape of query actually gets asked against them. A
structured version (typed min/max ranges, a typed load percentage/RPE
field) is a natural follow-up once that's clearer.

**Exercise swapping mid-training-block is unsupported.** Exercise
selection is fixed for an entire training block by design — every week's
prescription for that block points at the same exercise row. If a user
wants to swap one exercise for another partway through (an injury,
equipment unavailability, or an AI-assisted "swap squats for leg press, my
knee's bothering me" request), there's no clean way to represent it yet:
changing the exercise directly would retroactively rewrite history for
already-generated and already-cited weeks, and creating a whole new
training block just to represent a swap is heavyweight and breaks the
"one block is one coherent unit" semantics the schema is built around.
This likely needs either a validity range or an explicit "supersedes"
pointer between exercise rows — deliberately left undesigned until an
AI-assisted editing feature is actually being built, since that's the
feature that would determine the right shape.

**Cross-exercise volume coherence — resolved for whole-block generation.**
Volume research states weekly sets per muscle, so that weekly total is now
what gets generated and cited, once per muscle per training block; each
exercise's sets are a mechanical split of it (secondary work counted at
half, at most four sets per exercise for hypertrophy and five for strength),
and a plan that can't reach the cited target says so rather than cramming
the week into one exercise. The single-value edit paths below (regenerating
one week's sets, chat adjustments) still use the older shared-budget
guidance. Earlier approach, kept for context:
**Cross-exercise volume coherence — partially addressed.** Volume is
generated per exercise, so two exercises sharing a muscle group in the
same week could each be told the full research-backed range and together
overshoot the real weekly total for that muscle group. Volume generation
now gets told what's already been prescribed that week for other exercises
training the same muscle group, and is instructed to treat the research
range as a shared budget. Exercises that haven't been generated yet are
left out rather than reported as zero sets, since "not generated yet"
isn't the same as "confirmed free." This is guidance to the model, not an
enforced split: nothing checks the combined total after generation, and
the result depends on generation order (the first exercise generated sees
no siblings). A hard allocation step that divides the budget across
sibling exercises up front would close that gap. It needs no schema
change either way.

**Multi-muscle exercises — addressed with fractional set counting.** Each
exercise now has one primary muscle plus up to three secondary muscles. The
primary drives research retrieval and counts in full toward that muscle's
weekly volume; each secondary counts as half a set, so a set of rows adds
half a set to the lat budget without counting as a full lat set. The half
weighting is a fixed convention, not a research-derived per-exercise value
— a more precise version would weight contributions by exercise. Relatedly,
the muscle groups are now finer (lats vs. upper back, front/side/rear
delts), which sharpens exercise selection and the volume budget, but the
current corpus studies weekly volume in general rather than per muscle, so
retrieval surfaces the same evidence for every muscle until muscle-specific
research is added.

## Retrieval and generation

**Exercise selection is AI-chosen and uncited.** The program wizard has a
model pick exercises for each day of the chosen split. Each pick is
constrained to the muscle groups that day targets, and every target must be
covered, but no research backs which exercises were chosen — the corpus has
no exercise-selection literature, and citations attach to the generated
numbers, not to the program's structure. Exercise ordering (compound before
isolation) is requested but not enforced, and load generation still
produces a percentage-of-max value for bodyweight or isometric exercises
where that doesn't really apply. Grounding selection would need
exercise-selection research in the corpus and an exercise-level citation
target in the schema.

**Training goal isn't a hard filter on retrieved content, only a soft
semantic influence.** Research category (volume, frequency, intensity,
progression) is an exact-match filter on retrieval. Training goal
(hypertrophy vs. strength, etc.) isn't a filter at all — it's baked into
the natural-language query text, so it only influences results through
semantic similarity, not an explicit tag on the content. This doesn't
matter yet because the corpus doesn't yet have enough distinguishable
goal-specific content within the same category to need to choose between.
It will matter once the corpus has multiple papers specifically about
strength-goal dosing versus hypertrophy-goal dosing within the same
category — relying purely on semantic similarity to surface the right one
is weaker than an explicit filter would be, the same category of problem
the muscle-group field solved for exercise-to-muscle-group matching. The
likely fix is the same pattern already proven out: tag ingested content
with a goal field and add it as a second filter condition alongside the
existing category filter.

**No sub-category structure within the research corpus** (e.g.
volume-for-growth vs. volume-for-maintenance content). The staging
dataset is already organized by category *and* sub-topic, but content that
would blur that distinction (e.g. maintenance-phase dosing guidance) was
deliberately not ingested into the active pilot categories yet — flat
per-category retrieval can't yet distinguish "growth-phase volume
guidance" from "maintenance-phase volume guidance" within the same
category tag, so ingesting both now would mean irrelevant content
surfacing as "relevant" for a query it doesn't actually answer well.
Deferred until either the corpus is large enough or flat per-category
retrieval demonstrably needs finer filtering — the same underlying fix as
the goal-filtering gap above, likely resolved together.

**No user experience-level field anywhere upstream.** Dosing research
often states different ranges for different training experience levels
within the same source (e.g. "novices: 10-12 sets, advanced: 14-18 sets"
in one excerpt) — with no experience-level field on the user or program,
there's no way to know which stated range should even apply to a given
person, which affects both retrieval (surfacing the right range) and
citation verification (checking against the right range, not a
coincidentally-overlapping one for a different population). Doesn't matter
yet while a single excerpt stating one range for one population is still
the common case in a small corpus; will matter once dosing content
routinely carries multiple experience-level ranges. Likely fix: an
experience-level field threaded into query construction the same way
training goal already is, plus eventually a matching filter on ingested
content.

## Infrastructure

**Background job runner is in development mode only**, which is fine
while ingestion is an admin-run local operation, but not once any
user-facing feature depends on background jobs running in the deployed
environment — worth revisiting before any feature that could trigger
ingestion-like jobs in production (e.g. user-uploaded document processing).
