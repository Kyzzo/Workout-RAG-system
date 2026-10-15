"use client";

import { useState } from "react";
import { Alert, Book, ChevronRight, Close } from "./Icons";
import type { RuleJustification, SupportingCitation } from "./types";

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

function CitationItems({ citations }: { citations: SupportingCitation[] }) {
  return (
    <>
      {citations.map((c, i) => (
        <CitationItem key={i} citation={c} />
      ))}
    </>
  );
}

// One source: title and status, then its excerpt folded to a two-line
// preview - a panel can hold several long excerpts. Clicking the title row
// (or the preview) shows the whole excerpt.
function CitationItem({ citation: c }: { citation: SupportingCitation }) {
  const [open, setOpen] = useState(false);
  return (
    <figure className="flex flex-col gap-1.5">
      <figcaption>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="group/cite flex w-full items-start gap-1.5 text-start"
        >
          <ChevronRight
            className={`mt-[3px] size-3.5 shrink-0 text-fg-subtle transition-transform duration-200 group-hover/cite:text-fg ${open ? "rotate-90" : ""}`}
          />
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="font-medium text-fg">{c.citation.title}</span>
            <span
              className={`rounded-full px-1.5 py-px text-[11px] font-medium ${
                c.verification_status === "primary_support" ? "bg-evidence-soft text-evidence" : "bg-surface-3 text-fg-muted"
              }`}
            >
              {STATUS_LABEL[c.verification_status]}
            </span>
          </span>
        </button>
      </figcaption>
      <blockquote
        onClick={open ? undefined : () => setOpen(true)}
        className={`ms-5 whitespace-pre-line border-s-2 border-line-strong ps-3 leading-relaxed text-fg-muted ${
          open ? "animate-in" : "line-clamp-2 cursor-pointer"
        }`}
      >
        {c.citation.snippet}
      </blockquote>
    </figure>
  );
}

export function SourcesPanel({
  heading,
  citations,
  note,
  rule,
  onClose,
}: {
  heading: string;
  citations: SupportingCitation[];
  note: string | null;
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
      {note && <CaveatNote>{note}</CaveatNote>}
      <CitationItems citations={citations} />
      {rule && (
        <div className="flex flex-col gap-3 border-t border-line pt-3">
          <p className="font-semibold text-fg">{rule.heading}</p>
          <p className="text-fg-muted">{rule.justification.claim}</p>
          {rule.justification.grounding_note && <CaveatNote>{rule.justification.grounding_note}</CaveatNote>}
          <CitationItems citations={rule.justification.supporting_citations} />
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
