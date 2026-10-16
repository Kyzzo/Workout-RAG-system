"use client";

import { useEffect, useState } from "react";
import { Alert, Book, Close } from "./Icons";
import type { RuleJustification, SupportingCitation } from "./types";
import { Spinner } from "./ui";
import { useApi } from "./useApi";

// The two verification outcomes that count as evidence read differently to
// a user: one source states the value directly, the other informed it
// without stating it (see docs/design-decisions/citation-verification-pipeline.md).
const STATUS_LABEL: Record<SupportingCitation["verification_status"], string> = {
  primary_support: "States this directly",
  contextual_support: "Related evidence",
};

// A compact source count beside a value (book icon + number) - one per
// value, so a full label on each would drown the numbers. The accessible
// name and tooltip spell it out.
export function SourcesBadge({
  citations,
  note,
  open,
  onToggle,
  what,
}: {
  citations: SupportingCitation[];
  note: string | null;
  open: boolean;
  onToggle: () => void;
  what?: string;
}) {
  // A value with no verified source and no caveat hasn't been generated
  // (or was entered by hand) - nothing to show.
  if (citations.length === 0 && !note) return null;

  const count = citations.length;
  const full =
    count > 0
      ? `${count} verified source${count === 1 ? "" : "s"}${what ? ` for ${what}` : ""}`
      : `No verified source${what ? ` for ${what}` : ""} - see the note`;

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-label={`${open ? "Hide" : "Show"} ${full.toLowerCase()}`}
      title={full}
      className={`relative inline-flex h-5 items-center gap-0.5 rounded-full px-1.5 text-[11px] font-medium tabular-nums leading-none transition-[background-color,box-shadow] duration-150 after:absolute after:-inset-2 after:content-[''] ${
        count > 0 ? "bg-evidence-soft text-evidence" : "bg-warn-soft text-warn"
      } ${open ? "ring-1 ring-current" : ""}`}
    >
      {count > 0 ? <Book className="size-3" /> : <Alert className="size-3" />}
      {count > 0 ? count : "?"}
    </button>
  );
}

type Api = ReturnType<typeof useApi>;

// Combined summaries already fetched (or in flight) this session, keyed by
// question + citations, so reopening a panel doesn't ask again. A failed
// request is dropped so a later open retries it.
const summaries = new Map<string, Promise<string | null>>();

function combinedSummary(api: Api, question: string, citationIds: number[]): Promise<string | null> {
  const ids = [...new Set(citationIds)].sort((a, b) => a - b);
  const key = `${question}|${ids.join(",")}`;
  let pending = summaries.get(key);
  if (!pending) {
    pending = api<{ summary: string | null }>("/citations/summary", {
      method: "POST",
      body: { question, citation_ids: ids },
    }).then((r) => r.summary);
    pending.catch(() => summaries.delete(key));
    summaries.set(key, pending);
  }
  return pending;
}

// One plain-language answer to the panel's question, drawn from all of its
// studies together and checked against them server-side
// (POST /citations/summary). Nothing is shown if no summary passed.
function PanelSummary({ question, citations }: { question: string; citations: SupportingCitation[] }) {
  const api = useApi();
  const ids = citations.map((c) => c.citation.id);
  const idsKey = ids.join(",");
  // undefined: loading; null: none passed the check (or it couldn't load).
  const [summary, setSummary] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let stale = false;
    combinedSummary(api, question, idsKey ? idsKey.split(",").map(Number) : []).then(
      (s) => !stale && setSummary(s),
      () => !stale && setSummary(null),
    );
    return () => {
      stale = true;
    };
  }, [api, question, idsKey]);

  if (summary === undefined) {
    return (
      <p className="flex items-center gap-2 text-fg-subtle">
        <Spinner className="size-3.5 shrink-0" />
        Summarising {papersIn(citations).length} studies...
      </p>
    );
  }
  return summary ? <p className="text-sm leading-relaxed text-fg">{summary}</p> : null;
}

type Paper = { name: string; details: string; best: SupportingCitation["verification_status"]; excerpts: SupportingCitation[] };

// Excerpts grouped by paper ("Pelland et al. 2025" with two excerpts is one
// study), strongest verdict first.
function papersIn(citations: SupportingCitation[]): Paper[] {
  const byName = new Map<string, Paper>();
  for (const c of citations) {
    const [name, ...details] = c.citation.title.split(" · ");
    const paper = byName.get(name) ?? { name, details: details.join(" · "), best: c.verification_status, excerpts: [] };
    paper.excerpts.push(c);
    if (c.verification_status === "primary_support") paper.best = "primary_support";
    byName.set(name, paper);
  }
  return [...byName.values()].sort((a, b) => Number(b.best === "primary_support") - Number(a.best === "primary_support"));
}

// The studies behind a panel as a row of chips. One opens at a time:
// opening another switches to it, so the panel can't unfold into every
// excerpt at once.
function StudyList({ citations }: { citations: SupportingCitation[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const papers = papersIn(citations);
  if (papers.length === 0) return null;
  const open = papers.find((p) => p.name === selected);
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium text-fg-subtle">
        {papers.length} {papers.length === 1 ? "study" : "studies"}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {papers.map((paper) => {
          const active = paper.name === selected;
          return (
            <button
              key={paper.name}
              type="button"
              onClick={() => setSelected(active ? null : paper.name)}
              aria-expanded={active}
              title={STATUS_LABEL[paper.best]}
              className={`inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs transition-[background-color,border-color,color] duration-150 ${
                active
                  ? "border-accent bg-accent-soft text-fg"
                  : "border-line bg-surface text-fg-muted hover:border-line-strong hover:text-fg"
              }`}
            >
              <span
                aria-hidden="true"
                className={`size-1.5 rounded-full ${paper.best === "primary_support" ? "bg-evidence" : "bg-fg-subtle"}`}
              />
              {paper.name}
            </button>
          );
        })}
      </div>
      {open && (
        <div key={open.name} className="animate-in flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-subtle">
            <span className="font-medium text-fg">{open.name}</span>
            {open.details && <span>{open.details}</span>}
            <span
              className={`rounded-full px-1.5 py-px text-[11px] font-medium ${
                open.best === "primary_support" ? "bg-evidence-soft text-evidence" : "bg-surface-3 text-fg-muted"
              }`}
            >
              {STATUS_LABEL[open.best]}
            </span>
          </p>
          <div className="scroll-thin flex max-h-56 flex-col gap-2 overflow-y-auto">
            {open.excerpts.map((c, i) => (
              <blockquote
                key={i}
                className="whitespace-pre-line border-s-2 border-line-strong ps-3 leading-relaxed text-fg-muted"
              >
                {c.citation.snippet}
              </blockquote>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function SourcesPanel({
  heading,
  citations,
  note,
  question,
  rule,
  onClose,
}: {
  heading: string;
  citations: SupportingCitation[];
  note: string | null;
  // What the combined summary answers ("Why 8-12 reps for a hypertrophy
  // program?"). Without one, the panel shows its studies only.
  question?: string;
  // A mechanical rule that shaped this value (e.g. the even split of a
  // muscle's weekly sets across sessions), with its own verified sources.
  rule?: { heading: string; justification: RuleJustification } | null;
  // Shows a close button (the badge that opened the panel also closes it).
  onClose?: () => void;
}) {
  return (
    <div className="animate-in mt-2 flex flex-col gap-3 rounded-xl border border-line bg-surface-2/70 p-3.5 text-[13px]">
      <div className="flex items-start gap-2">
        <p className="flex flex-1 items-center gap-2 font-semibold text-fg">
          <Book className="size-3.5 shrink-0 text-evidence" />
          {heading}
        </p>
        {onClose && (
          <button type="button" onClick={onClose} className="icon-btn -me-1.5 -mt-1.5 size-7" aria-label="Close sources">
            <Close className="size-3.5" />
          </button>
        )}
      </div>
      {question && citations.length > 0 && <PanelSummary question={question} citations={citations} />}
      {note && <CaveatNote>{note}</CaveatNote>}
      <StudyList citations={citations} />
      {rule && (
        // The rule's claim was checked against each of its sources, so it
        // is this section's summary.
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <p className="font-semibold text-fg">{rule.heading}</p>
          <p className="text-sm leading-relaxed text-fg">{rule.justification.claim}</p>
          {rule.justification.grounding_note && <CaveatNote>{rule.justification.grounding_note}</CaveatNote>}
          <StudyList citations={rule.justification.supporting_citations} />
        </div>
      )}
    </div>
  );
}

// A grounding caveat ("no source states this directly...") - amber with
// an icon, so it isn't carried by colour alone.
export function CaveatNote({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={`flex items-start gap-1.5 text-warn ${className}`}>
      <Alert className="mt-[3px] size-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}
