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
2. **Drop what can't be evidence.** Each paper is split at its References
   heading when it's ingested, so its bibliography becomes separate,
   tagged excerpts that the search itself leaves out — a reference list
   names the very topics a question asks about, so it matches well but
   states no findings, and in the per-paper pass it used to take a paper's
   few slots. Duplicate excerpts (a paper filed under two categories) are
   removed too.
3. **Rerank by meaning.** A small model scores every candidate 0–10 for
   how well it *answers the question* — a finding that directly answers it
   for the right outcome scores high; an introduction, methods passage or
   a finding for a different outcome scores low. Statistical results count
   as answers even when they share no words with the question. Candidates
   are scored in batches of 15, in parallel: sent all at once (100+
   excerpts once the corpus reached 26 papers), the scores went
   near-uniform and stopped separating answers from background.
4. **Pick for relevance first, then spread.** Excerpts scoring at least 4
   are taken first, at most two per paper so one study can't fill every
   slot, then backfilled; weaker excerpts only fill leftover room, and are
   spread across papers the same way. Ten excerpts for a generated value,
   fifteen for a chat answer.

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

Growing the corpus from 14 to 26 papers surfaced two more:

- **Bibliographies taking slots.** For a rep-range question, the per-paper
  pass gave two load meta-analyses three slots each — mostly their
  reference lists, which the citation-pattern detector missed in some
  journals' formats. Their findings never reached the reranker, and one
  review supplied 8 of 10 excerpts. Splitting papers at the References
  heading fixed this for every citation style at once.
- **Too many excerpts per reranker call** (above): scored in one call, a
  frequency question gave 10/10 to most excerpts of unrelated
  proximity-to-failure papers. Batching restored discrimination.

After both: 39 of 40 expected papers. The one miss was a meta-analysis
whose findings ranked below its discussion for one long, templated
generation question - fixed by the next change.

## Search with the topic, judge with the question

A generation question names exercises and asks for a format ("answer with
a rep range like '8-12'"), which pulled similarity toward passages that
mention exercises rather than ones that report results. The similarity
search now embeds a short statement of the topic ("Proximity to failure
(repetitions in reserve) and maximal strength (1RM)"); the reranker,
generator and judge still see the full question, so what counts as an
answer is unchanged. With it, every affected check passes, including the
previous miss.

## Same outcome isn't the same question

With 35 papers, the small reranker model started rewarding excerpts that
shared the question's outcome but not its subject: a muscle-damage study
scored 10/10 for a question about deload weeks, and a trial's methods
section ranked above its results. The rubric now says an excerpt must be
about what the question is about — a finding on a different training
variable scores 1–3 even for the same outcome — and the reranker is the
full-size model: on those cases it dropped the damage study to ~2 and put
the results first, where the small model with the same rubric did not.
It costs about five times as much per excerpt. To offset that, chat (which
searches the whole corpus) now takes the best two excerpts from the 15
best-matching papers rather than three from every paper: 110-120 excerpts
per question became ~56, about $0.05 a question, with every chat check
still passing. A generation question reranks ~50 excerpts (~$0.04), paid
once per shared answer.

## Cost

A few small-model calls per retrieval (one per batch of 15 candidates, in
parallel — about the same total tokens as a single call). Chat pays it once per question (a few
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

- **Thin categories.** Reranking can't conjure evidence that isn't there.
  Rep ranges and progression each rested on one paper until the corpus
  grew to 26; recovery still rests on two.
- **The reranker is still a filter, not a judge.** It decides what the
  judge gets to see; the judge decides what counts as support.
