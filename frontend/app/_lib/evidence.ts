import type { Api } from "../useApi";
import type {
  CitationOut,
  ExerciseSlot,
  Mesocycle,
  MuscleGroupFrequency,
  MuscleGroupVolume,
  Program,
  ProgressionScheme,
  RuleJustification,
  SupportingCitation,
  WeeklyPrescription,
} from "../types";
import { isPlaceholder, paperOf, schemeLabel, titleDetails } from "./format";

export type ValueField = "sets" | "reps" | "load" | "rir";

// Everything the sources view needs for one cited value.
export type SourcesRequest = {
  heading: string;
  // The summary question (Appendix A.2 templates - server cache keys, so
  // never reworded). null: no combined summary is asked for.
  question: string | null;
  citations: SupportingCitation[];
  note: string | null;
  // Sets that are a mechanical share of the muscle's weekly volume also show
  // the rule for spreading sets evenly across sessions.
  splitRule?: boolean;
};

export type SourcesState = { kind: "cited"; count: number } | { kind: "note" } | { kind: "none" };

export function sourcesState(req: SourcesRequest | null): SourcesState {
  if (!req) return { kind: "none" };
  if (req.citations.length) return { kind: "cited", count: req.citations.length };
  if (req.note) return { kind: "note" };
  return { kind: "none" };
}

export const FIELD_NAMES: Record<ValueField, string> = { sets: "sets", reps: "reps", load: "load", rir: "effort" };

function volumeFor(block: Mesocycle, muscle: string): MuscleGroupVolume | undefined {
  return block.muscle_group_volumes.find((v) => v.muscle_group === muscle);
}

export function volumeQuestion(weeklySets: number, goal: string) {
  return `Why ${weeklySets} weekly sets per muscle in a ${goal} program?`;
}

export function valueSources(
  program: Program,
  block: Mesocycle | null,
  slot: ExerciseSlot,
  p: WeeklyPrescription,
  field: ValueField,
): SourcesRequest | null {
  if (isPlaceholder(p)) return null;
  const goal = program.goal;
  switch (field) {
    case "sets": {
      const note = p.sets_grounding_note;
      const heading = `Why ${p.sets} ${p.sets === 1 ? "set" : "sets"}`;
      const splitRule = !!note?.startsWith("Share of");
      if (p.sets_citations.length) {
        return { heading, question: `Why ${p.sets} sets for a ${goal} program?`, citations: p.sets_citations, note, splitRule };
      }
      // No citations of its own: the sets are a split of the muscle's
      // weekly volume, so that volume's sources and question stand in.
      const volume = block ? volumeFor(block, slot.muscle_group) : undefined;
      if (volume && volume.supporting_citations.length) {
        return {
          heading,
          question: volumeQuestion(volume.weekly_sets, goal),
          citations: volume.supporting_citations,
          note,
          splitRule,
        };
      }
      return { heading, question: null, citations: [], note, splitRule };
    }
    case "reps": {
      const scheme = block?.progression_schemes.find((s) => s.muscle_group === slot.muscle_group)?.scheme;
      const linearPhase = goal === "strength" && scheme === "linear" && !!p.reps_grounding_note?.startsWith("Phase ");
      const question = linearPhase
        ? `Why ${p.reps} reps in this phase of linear progression, for a ${program.trained ? "trained lifter" : "lifter newer to training"} with a strength goal?`
        : `Why ${p.reps} reps for a ${goal} program?`;
      return { heading: `Why ${p.reps} reps`, question, citations: p.reps_citations, note: p.reps_grounding_note };
    }
    case "load":
      if (!p.load) return null;
      return {
        heading: `Why ${p.load}`,
        question: `Why ${p.load} load for a ${goal} program?`,
        citations: p.load_citations,
        note: p.load_grounding_note,
      };
    case "rir":
      return {
        heading: `Why ${p.rir}`,
        question: `Why ${p.rir} effort (RIR) for a ${goal} program?`,
        citations: p.rir_citations,
        note: p.rir_grounding_note,
      };
  }
}

export function volumeSources(volume: MuscleGroupVolume, goal: string): SourcesRequest {
  return {
    heading: `Why research suggests ${volume.weekly_sets} weekly sets per muscle`,
    question: volumeQuestion(volume.weekly_sets, goal),
    citations: volume.supporting_citations,
    note: volume.grounding_note,
  };
}

export function frequencySources(freq: MuscleGroupFrequency, goal: string, who: string): SourcesRequest {
  return {
    heading: `Why research suggests ${freq.frequency}x/week for ${who}`,
    question: `Why train each muscle ${freq.frequency}x a week for ${goal}?`,
    citations: freq.supporting_citations,
    note: freq.grounding_note,
  };
}

export function progressionSources(scheme: ProgressionScheme, program: Program): SourcesRequest {
  if (scheme.scheme === "constant") {
    return {
      heading: `Why ${scheme.muscle_group} has no scheduled progression`,
      question: null,
      citations: scheme.supporting_citations,
      note: scheme.grounding_note,
    };
  }
  const label = schemeLabel(scheme.scheme);
  const why = program.trained ? "you've lifted consistently for 1+ year" : "you're newer to lifting";
  return {
    heading: `Why ${label} progression: ${why}`,
    question: `Why ${label} progression for ${program.goal}?`,
    citations: scheme.supporting_citations,
    note: scheme.grounding_note,
  };
}

// ---- Studies, grouped by paper ----

export type Verdict = "primary_support" | "contextual_support";

export const VERDICT_TEXT: Record<Verdict, string> = {
  primary_support: "States this directly",
  contextual_support: "Related evidence",
};

export type Study = { paper: string; details: string[]; verdict: Verdict; citationIds: number[] };

export function groupStudies(citations: SupportingCitation[]): Study[] {
  const byPaper = new Map<string, Study>();
  for (const c of citations) {
    const paper = paperOf(c.citation.title);
    let study = byPaper.get(paper);
    if (!study) {
      study = { paper, details: [], verdict: c.verification_status, citationIds: [] };
      byPaper.set(paper, study);
    }
    const detail = titleDetails(c.citation.title);
    if (detail && !study.details.includes(detail)) study.details.push(detail);
    if (!study.citationIds.includes(c.citation.id)) study.citationIds.push(c.citation.id);
    if (c.verification_status === "primary_support") study.verdict = "primary_support";
  }
  const studies = [...byPaper.values()];
  // Primary first; otherwise keep the server's order.
  return studies
    .map((s, i) => ({ s, i }))
    .sort((a, b) => (a.s.verdict === b.s.verdict ? a.i - b.i : a.s.verdict === "primary_support" ? -1 : 1))
    .map(({ s }) => s);
}

export function summaryIds(citations: SupportingCitation[]): number[] {
  return [...new Set(citations.map((c) => c.citation.id))].sort((a, b) => a - b).slice(0, 20);
}

// ---- Per-page-session caches. The promise is cached so concurrent opens
// share one request; a failure is evicted so a later open retries. ----

const excerpts = new Map<number, Promise<CitationOut>>();
const summaries = new Map<string, Promise<string | null>>();
const rules = new Map<string, Promise<RuleJustification>>();

function remember<K, V>(cache: Map<K, Promise<V>>, key: K, load: () => Promise<V>): Promise<V> {
  const hit = cache.get(key);
  if (hit) return hit;
  const promise = load();
  cache.set(key, promise);
  promise.catch(() => {
    if (cache.get(key) === promise) cache.delete(key);
  });
  return promise;
}

export function loadExcerpt(api: Api, id: number): Promise<CitationOut> {
  return remember(excerpts, id, () => api<CitationOut>(`/citations/${id}`));
}

export function summaryKey(question: string, ids: number[]): string {
  return `${question}|${ids.join(",")}`;
}

export function loadSummary(api: Api, question: string, ids: number[]): Promise<string | null> {
  return remember(summaries, summaryKey(question, ids), () =>
    api<{ summary: string | null }>("/citations/summary", {
      method: "POST",
      body: { question, citation_ids: ids },
    }).then((r) => r.summary),
  );
}

export function loadRule(api: Api, key: string): Promise<RuleJustification> {
  return remember(rules, key, () => api<RuleJustification>(`/rules/${key}`));
}
