# Initial Planning Documents

These are the plans written before any code, committed with the first
scaffold on July 14, 2026. They are kept unedited as a record of where the
project started. Status marks such as DONE were added to the phase plan as
work finished, so it doubles as a progress log.

| File | What it is |
|---|---|
| [phases.txt](phases.txt) | The build order, phase by phase, with status notes added along the way |
| [phase1.txt](phase1.txt) | A detailed plan for the first phase: backend skeleton and CRUD, no AI |
| [datamodel.txt](datamodel.txt) | The relational schema, plus design problems deliberately deferred (code comments still point here) |
| [TechStack.txt](TechStack.txt) | The chosen stack and how the pieces connect |
| [TechStackExplained.txt](TechStackExplained.txt) | Study notes on what each piece of the stack does |

## What held up

- **Build order.** Prove the hardest mechanic on one research category
  (volume) before generalizing, then repeat the pattern for frequency,
  intensity and progression. That order was followed.
- **Data model.** Numbers are stored per exercise, per week, which is what
  let citations attach to a single value instead of a whole program.
- **Stack.** FastAPI, Postgres, Qdrant, Inngest, OpenAI, Next.js and Clerk
  all shipped as planned. Deployment happened early, right after phase 1.

## What the plan got wrong or didn't foresee

- **Citations needed checking, not just recording.** The plan was to have
  the model name the excerpts it used for each value. In practice a model's
  self-reported citation is often wrong, so every citation now goes through
  a [verification pipeline](../docs/design-decisions/citation-verification-pipeline.md).
- **Similarity search wasn't enough.** It ranked excerpts by wording rather
  than by whether they answered the question, which led to
  [per-paper retrieval and reranking](../docs/design-decisions/retrieval-and-reranking.md).
- **Cost.** Verifying every number with a strong model cost about 590
  large-model calls per program. Storing verified answers for reuse
  brought that to 29 for the first program of a setup and none after. See
  [shared research answers](../docs/design-decisions/shared-research-answers.md).
- **Chat answers needed sentence-level checks.** One answer had correct
  citations and a wrong claim, so chat answers are now verified claim by
  claim. The [accuracy hardening log](../docs/engineering-log/accuracy-hardening.md)
  tells that story.
- **User document upload was cut.** It was designed but deferred for cost.
