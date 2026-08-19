# Design Decision: Field-Level Citation Attribution

Most RAG systems that "cite sources" do it at the response level: retrieve
some chunks, generate an answer, list the chunks used somewhere nearby.
This project does something harder — it attributes each individually
generated value to its own specific source, independently of every other
value in the same response.

## The concept

**Response-level citation** treats a whole generated answer as one unit,
attributed to an aggregate list of sources: "here are the N chunks that
informed this answer." There's no claim about which specific part of the
answer came from which specific source. This is mechanically simple — the
set of chunks retrieved for a request *is* the citation list — and it's
what most RAG products do (Perplexity, Copilot, ChatGPT with browsing,
most RAG framework defaults).

**Field-level (parameter-level) attribution** attributes each individual
generated *value* to its own source(s), independently of every other value
in the same response. In this project: not "here's your program, and here
are 20 papers somewhere in the mix," but "this specific number — 3 sets of
squats in week 2 — is backed by this specific study, and that other
number — 8-10 reps for bench press — is backed by a different study." A
single training program contains dozens of independent numeric decisions
(one row per exercise per week), and each one can trace to different
evidence.

## Why field-level is genuinely harder

Response-level citation needs no real bookkeeping. Field-level requires a
separate, correct attribution decision for *every* generated field, and
there are two real ways to attempt it, each with a real failure mode:

- Have the model report its own source chunk IDs alongside each value.
  Risk: the model can still hallucinate a plausible-looking chunk ID, or
  genuinely misattribute — reporting a citation isn't the same as the
  citation being true.
- Post-hoc similarity matching between each generated field and the
  retrieved chunks. Weaker still: the model may generate a value from its
  own training knowledge first, and a similarity matcher can then find a
  superficially related chunk that never actually determined that value —
  a citation that *looks* grounded but isn't.

Neither is a solved, off-the-shelf pattern the way basic retrieval or
response-level citation are. (Some legal-tech and clinical decision-
support tools do source-grounded extraction at roughly this granularity,
so this isn't unprecedented — just meaningfully harder than the
response-level default, not something nobody has attempted.)

## Why this product specifically needs it

This isn't chosen because it's more impressive — response-level citation
would be close to meaningless for this product's shape. A single-answer
Q&A chatbot ("what's the best rep range for hypertrophy?") is basically
one coherent claim, so one aggregate source list covers it fine.

A generated training program is structurally different: a bundle of dozens
of quasi-independent numeric decisions — sets, reps, load, progression —
for every exercise, every week, across potentially multiple training
blocks. Volume, intensity, and progression guidance typically come from
different lines of research entirely. Offering "here are 15 sources for
your whole program" tells the user nothing about *which* source justifies
*which* number — the citation list becomes decorative, not actually
auditable, precisely because the response bundles so many independent
claims together.

This shaped the data model from the start rather than being retrofitted:
"week" only enters the schema as a column on the lowest-level table
(`WeeklyPrescription`) specifically because that's where citations need to
attach — the research-backed claim is about the numbers for a given week,
not the one-time choice of which exercises are in the program.

## What this buys the user

- **Trust and verifiability** — a user can inspect any individual number
  and see the actual study behind it, rather than trusting an opaque
  aggregate claim.
- **Informed override** — sports-science research on training variables is
  genuinely contested. If a user disagrees with a specific number, field-
  level attribution shows exactly which study drove that choice, so they
  can make an informed decision about overriding it. Response-level
  citation can't support this — there's no way to know which of 15 cited
  papers actually determined the one number in question.
- **Surfaces disagreement instead of hiding it** — since different
  prescriptions can cite different, even conflicting, studies, this makes
  visible that "training volume" is a genuinely debated variable, rather
  than blending everything into one confident-sounding average.
- **Real differentiation** — most "AI-generated workout" tools either cite
  nothing or cite vaguely. Answering "why 3 sets and not 4, specifically"
  with a real, traceable source is a tangible difference, not a marketing
  claim.

## The pragmatic fallback

Field-level attribution is the target because it's what makes "grounded
and auditable" true at the granularity that actually matters here — but
it's treated as an ambitious target with a deliberate, pre-planned
fallback, not an all-or-nothing bet: if the core "map a generated field to
its source chunk" mechanism isn't proven reliable for at least one field
by a set checkpoint, the plan explicitly cuts scope to response-level
citation rather than letting an unproven mechanism eat into the rest of
the build.

## Three modes, not two

In practice, the product ended up needing three distinct modes rather than
a single either/or choice between response-level and field-level:

1. **Field-level generation/editing** — a value is being generated or
   changed for a specific exercise/week ("give me a program," "change this
   to 4 sets"). Full field-level attribution, fully verified.
2. **Field-level discussion** — a user asks about an already-generated,
   already-verified value ("why is this 5-8 reps"). No new generation or
   verification needed — the already-stored verdict and citation are
   simply surfaced.
3. **General-knowledge Q&A** — a question not tied to any specific
   persisted value ("what does research say about training to failure").
   Response-level citation is the *correct* fit here, not a fallback —
   there's no single field-level claim to pin a citation to, and this mode
   matters for making the product useful to someone who wants to
   understand the underlying principles, not just override specific
   numbers.
