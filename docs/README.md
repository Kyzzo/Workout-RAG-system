# Documentation Index

This is a RAG-backed workout program generator with a specific, harder
goal than most "AI fitness" tools: instead of citing sources for a whole
generated program in aggregate, it attributes each individual generated
number — sets, reps, load, for a specific exercise, in a specific week —
to its own verified source, so a user can inspect and trust (or
knowingly override) any single value rather than a program's numbers all
at once.

**Start here if you only read one thing:**
[Field-Level Citation Attribution](design-decisions/field-level-citation-attribution.md)
explains what that actually means and why it's harder than the response-
level citation most RAG products do. Its companion,
[Citation Verification Pipeline](design-decisions/citation-verification-pipeline.md),
covers how a self-reported citation gets checked against reality instead
of trusted outright.

## Design decisions

The *why* behind the harder architectural choices.

- [Field-Level Citation Attribution](design-decisions/field-level-citation-attribution.md) —
  what per-parameter citation is, and why response-level citation would be
  close to meaningless for this product's shape.
- [Citation Verification Pipeline](design-decisions/citation-verification-pipeline.md) —
  how a self-reported citation is checked, not just trusted; the core
  differentiator's actual mechanism.
- [Chat Interface Routing](design-decisions/chat-interface-routing.md) —
  routing a chat message to the right handling mode (edit, discuss, or
  general research question) without trusting a model-supplied identifier,
  and why answers ended up verified sentence by sentence.
- [Retrieval and Reranking](design-decisions/retrieval-and-reranking.md) —
  why similarity search ranks wording rather than answers, and how
  per-paper candidates plus a reranker took expected-paper recall to 23/23.
- [Shared Research Answers](design-decisions/shared-research-answers.md) —
  asking each research question at the level the research answers it and
  storing verified answers for reuse: ~590 large-model calls per program
  down to 29 for the first of a setup and 0 after, without weakening
  verification.
- [Research-Bounded Program Options](design-decisions/research-bounded-program-options.md) —
  tying user-facing choices (volume, frequency) and mechanical rules to
  cited evidence, and what the options said before they were.

## Engineering log

The *how it was actually built*, including the real bugs testing against
real data caught — not just a polished summary.

- [Auth and Data Layer](engineering-log/auth-and-data-layer.md) — JWT
  verification without a shared secret, a security-driven migration away
  from path-matching-based authorization, and the ORM/migration layer
  underneath it.
- [Frontend UI Notes](engineering-log/frontend-ui-notes.md) — server vs.
  client component boundaries, bridging a separate backend's auth
  boundary, and a couple of real UI bugs.
- [Deployment and CI/CD](engineering-log/deployment-and-cicd.md) — the
  monorepo root-directory problem on two different platforms, a
  build-time environment variable trap, and the gap between a platform
  showing "connected" and push events actually arriving.
- [RAG Ingestion Build](engineering-log/rag-ingestion-build.md) —
  durable background jobs for ingestion, a two-collection privacy
  boundary, and a required-index bug that would have silently broken on
  every future reset.
- [Structured Generation Build](engineering-log/structured-generation-build.md) —
  the retrieval-to-generation pipeline, and the testing discipline used
  to prove it actually worked rather than just looked like it did.
- [Citation Verification Build](engineering-log/citation-verification-build.md) —
  building the verification pipeline, and the real precision gaps found
  only by testing against messy real corpus data instead of clean
  hand-written examples.
- [Accuracy Hardening](engineering-log/accuracy-hardening.md) — a chat
  answer with correct citations and an incorrect claim, and everything it
  led to: statement-level verification, choosing the judge model by
  measurement, bugs only real runs exposed, a regression harness for
  judgment, and the cost work that followed.

## What's next

- [Future Work and Known Limitations](future-work.md) — deliberately
  deferred design questions, with reasoning for why each doesn't matter
  yet and what would make it matter.
