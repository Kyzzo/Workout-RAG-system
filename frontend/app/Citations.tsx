import type { RuleJustification, SupportingCitation } from "./types";

// The two verification outcomes that count as evidence read differently to
// a user: one source states the value directly, the other informed it
// without stating it (see docs/design-decisions/citation-verification-pipeline.md).
const STATUS_LABEL: Record<SupportingCitation["verification_status"], string> = {
  primary_support: "states this directly",
  contextual_support: "related evidence",
};

export function SourcesBadge({
  citations,
  note,
  open,
  onToggle,
}: {
  citations: SupportingCitation[];
  note: string | null;
  open: boolean;
  onToggle: () => void;
}) {
  // A value with no verified source and no caveat hasn't been generated
  // (or was entered by hand) - nothing to show.
  if (citations.length === 0 && !note) return null;

  const label =
    citations.length > 0 ? `${citations.length} source${citations.length === 1 ? "" : "s"}` : "no source";
  const tone =
    citations.length > 0
      ? "border-green-600 text-green-700 dark:border-green-500 dark:text-green-400"
      : "border-amber-500 text-amber-600";

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={`text-[11px] leading-none border rounded-full px-1.5 py-0.5 ml-1 ${tone} ${open ? "font-semibold" : ""}`}
    >
      {label}
    </button>
  );
}

function CitationItems({ citations }: { citations: SupportingCitation[] }) {
  return (
    <>
      {citations.map((c, i) => (
        <div key={i} className="flex flex-col gap-1">
          <p>
            <span className="font-medium">{c.citation.title}</span>{" "}
            <span className="text-zinc-500">- {STATUS_LABEL[c.verification_status]}</span>
          </p>
          <p className="text-zinc-600 dark:text-zinc-400 max-h-32 overflow-y-auto whitespace-pre-line bg-white dark:bg-zinc-900 border rounded p-2">
            {c.citation.snippet}
          </p>
        </div>
      ))}
    </>
  );
}

export function SourcesPanel({
  heading,
  citations,
  note,
  rule,
}: {
  heading: string;
  citations: SupportingCitation[];
  note: string | null;
  // A mechanical rule that shaped this value (e.g. the even split of a
  // muscle's weekly sets across sessions), with its own verified sources.
  rule?: { heading: string; justification: RuleJustification } | null;
}) {
  return (
    <div className="flex flex-col gap-2 mt-1 mb-2 border-l-2 border-green-600 dark:border-green-500 pl-3 py-1 text-xs">
      <p className="font-medium text-zinc-700 dark:text-zinc-300">{heading}</p>
      {note && <p className="text-amber-600">{note}</p>}
      <CitationItems citations={citations} />
      {rule && (
        <div className="flex flex-col gap-2 mt-2 pt-2 border-t">
          <p className="font-medium text-zinc-700 dark:text-zinc-300">{rule.heading}</p>
          <p className="text-zinc-500">{rule.justification.claim}</p>
          {rule.justification.grounding_note && (
            <p className="text-amber-600">{rule.justification.grounding_note}</p>
          )}
          <CitationItems citations={rule.justification.supporting_citations} />
        </div>
      )}
    </div>
  );
}
