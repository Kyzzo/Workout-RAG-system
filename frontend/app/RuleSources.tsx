"use client";

import { useState } from "react";
import { SourcesPanel } from "./Citations";
import type { RuleJustification } from "./types";
import { useApi } from "./useApi";

// A short explanation of one of the app's cited rules, with a "sources"
// toggle that fetches the rule's verified excerpts on first open. With two
// rules, the second shows under the first (e.g. the frequency finding and
// the per-session reason that supports training more often).
export function RuleSources({
  text,
  ruleKeys,
  secondHeading,
}: {
  text: React.ReactNode;
  ruleKeys: [string] | [string, string];
  secondHeading?: string;
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
    <div className="text-xs text-zinc-500">
      <p>
        {text}{" "}
        <button type="button" onClick={toggle} className="underline">
          {open ? "hide sources" : "sources"}
        </button>
      </p>
      {open &&
        (first ? (
          <SourcesPanel
            heading={first.claim}
            citations={first.supporting_citations}
            note={first.grounding_note}
            rule={second ? { heading: secondHeading ?? second.claim, justification: second } : null}
          />
        ) : (
          <p className={error ? "text-red-600" : ""}>{error ?? "Loading sources..."}</p>
        ))}
    </div>
  );
}
