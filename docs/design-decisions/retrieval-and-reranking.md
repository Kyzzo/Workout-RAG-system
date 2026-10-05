# Design Decision: Retrieval and Reranking

Verification decides whether a cited excerpt supports a value — but it can
only judge excerpts that retrieval found. Several accuracy problems in
this project turned out to be retrieval problems wearing a different
costume. This document covers how retrieval chooses evidence now, and the
measured failures behind each piece.

## Similarity ranks wording, not answers

Retrieval starts with embedding similarity: excerpts whose wording is
closest to the question come first. That's a good way to gather
candidates and a poor way to choose evidence. Three failures from real
questions:

- Asked for the most effective weekly set *range*, the top five excerpts
  were three passages from a rep-*range* paper, a reference list, and one
  relevant study — the volume meta-analyses never appeared.
- Weekly volume for hypertrophy drew three of its five excerpts from a
  single eight-week study of very strong lifters, and none from the
  largest volume meta-analysis.
- Asked whether training a muscle three times a week beats twice, retrieval
  returned eight excerpts of the study titled "…Two Versus Three Days Per
  Week" — and not the meta-analysis result that answers the question most
  directly, because it's written as "the marginal slope of the
  dose-response between frequency and hypertrophy was 0.32%", which shares
  almost no wording with the question.

## The pipeline now

1. **Gather candidates broadly.** The nearest excerpts by similarity
   (filtered to the field's research category for generation; the
   categories a chat question mentions plus the whole corpus for chat),
   **plus the best few excerpts from every paper** in scope. The per-paper
   pass exists because the top-N by similarity often came from just three
   papers, so a meta-analysis phrased differently never even became a
   candidate.
2. **Drop what can't be evidence.** Duplicate excerpts (a paper filed under
   two categories) and reference lists (detected by repeated
   journal-citation patterns) are removed.
3. **Rerank by meaning.** A small model scores every candidate 0–10 for
   how well it *answers the question* — a finding that directly answers it
   for the right outcome scores high; an introduction, methods passage or
   a finding for a different outcome scores low. Statistical results count
   as answers even when they share no words with the question.
4. **Pick for relevance first, then spread.** Excerpts scoring at least 4
   are taken first, at most two per paper so one study can't fill every
   slot, then backfilled by score; weaker excerpts only fill leftover room.
   Ten excerpts for a generated value, fifteen for a chat answer.

If the reranker fails, retrieval falls back to similarity order — reranking
improves evidence, it isn't allowed to break generation.

## Measured, not assumed

A retrieval check lists, for every generated value and several chat
questions, the papers that *should* come back (for example: weekly volume
for hypertrophy must include the largest volume meta-analysis), and
reports which ones did. It asks the same questions generation actually
asks. Building reranking against it surfaced two bugs that would otherwise
have shipped quietly:

- **Skipped scores.** With a free-form list of scores, the first reranker
  model scored only 3 of 40 candidates; the rest defaulted to zero and
  were treated as irrelevant, which collapsed evidence to two or three
  papers. The response format now has one required score per excerpt, so
  none can be skipped.
- **A weak reranker.** The same model scored "no statistically significant
  difference between training to failure and not" as *unrelated* to a
  question about how close to failure to train. A slightly larger model
  scored it as relevant at similar speed (~2.5 s); a reasoning model scored
  about the same but took 4–15 s.

Result: all expected papers retrieved (23 of 23), with most questions
drawing on five to ten papers at most two excerpts each — where before one
paper often supplied five to nine.

## Cost

One small-model call per retrieval. Chat pays it once per question (a few
percent of an answer's cost, since each answer already makes many judge
calls). Generation pays it only when a [shared answer](shared-research-answers.md)
is first created, so per program it's effectively zero. It can also save
cost: better evidence means fewer weak citations for the judge to reject
and fewer retries.

## Paper metadata

Every paper is listed in a corpus manifest with its study type
(meta-analysis, randomized trial, review), the outcome it measured
(hypertrophy, strength or both), its population (trained, untrained or
mixed), year and publication status, and those tags are stored on each of
its excerpts. That changes three things:

- **Goal filtering is exact.** A strength program or question only
  considers strength and both-outcome papers; a hypertrophy one only
  hypertrophy and both. Wording-based ranking and the reranker couldn't
  reliably tell outcomes apart (a squat-strength finding had been cited
  for hypertrophy volume). If filtering would leave fewer than two papers,
  retrieval falls back to everything rather than citing a single study.
- **Every model sees what kind of evidence it's reading.** Excerpts reach
  the generator, reranker and judge labeled ("Pelland et al. 2025 ·
  meta-analysis · hypertrophy and strength · mixed training status"), so
  "weigh meta-analyses over single studies" and "don't generalize beyond
  the population studied" act on facts rather than inference. The same
  label is what users see on each source.
- **Ingestion refuses untagged papers**, and the manifest made duplicates
  visible: two papers had been stored twice (once per category); each is
  now one copy serving both categories.

## What's still missing

- **Thin categories.** Reranking can't conjure evidence that isn't there:
  rep ranges rest on one paper and progression on one. More papers matter
  more than any retrieval tuning for those.
- **The reranker is generous.** It sometimes scores a hypertrophy finding
  highly for a strength question. That's tolerable because the judge, not
  the reranker, decides what counts as support — reranking only decides
  what the judge gets to see.
