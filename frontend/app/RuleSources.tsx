"use client";

import { useState } from "react";
import { SourcesPanel } from "./Citations";
import { Book } from "./Icons";
import type { RuleJustification } from "./types";
import { useApi } from "./useApi";

// A short explanation of one of the app's cited rules, with a "Sources"
// toggle that fetches the rule's verified excerpts on first open. With two
// rules, the second shows under the first (e.g. the frequency finding and
// the per-session reason that supports training more often).
export function RuleSources({
  text,
  ruleKeys,
  secondHeading,
  label,
}: {
  text: React.ReactNode;
  ruleKeys: [string] | [string, string];
  secondHeading?: string;
  // A short topic shown before the text ("Volume", "Loads"...).
  label?: string;
}) {
  const api = useApi();
  const [rules, setRules] = useState<RuleJustification[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    const opening = !open;
    setOpen(opening);
    if (!opening || rules) return;
    setError(null);
    try {
      setRules(await Promise.all(ruleKeys.map((key) => api<RuleJustification>(`/rules/${key}`))));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const [first, second] = rules ?? [];
  return (
    <div className="text-sm leading-relaxed text-fg-muted">
      <p>
        {label && <span className="font-medium text-fg">{label}. </span>}
        {text}{" "}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="inline-flex translate-y-[-1px] items-center gap-1 rounded-full bg-evidence-soft px-2 py-0.5 align-middle text-xs font-medium text-evidence transition-[box-shadow] hover:ring-1 hover:ring-current"
        >
          <Book className="size-3" />
          {open ? "Hide sources" : "Sources"}
        </button>
      </p>
      {open &&
        (first ? (
          <SourcesPanel
            heading={first.claim}
            citations={first.supporting_citations}
            note={first.grounding_note}
            onClose={() => setOpen(false)}
            rule={second ? { heading: secondHeading ?? second.claim, justification: second } : null}
          />
        ) : (
          <p className={`mt-2 text-xs ${error ? "text-danger" : "text-fg-subtle"}`}>{error ?? "Loading sources..."}</p>
        ))}
    </div>
  );
}
