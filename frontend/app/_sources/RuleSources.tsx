"use client";

import { useId, useState } from "react";
import { loadRule } from "../_lib/evidence";
import type { RuleExplanation } from "../_lib/research";
import { useApi } from "../_state/session";
import { Icon } from "../_ui/Icon";
import type { RuleJustification } from "../types";
import { errorMessage } from "../useApi";
import { StudyList } from "./StudyList";

// An explanation of one or two cited rules, with their sources on demand.
// No combined summary is asked for: rule claims were already checked
// against their sources.
export function RuleSources({ rule, compact = false }: { rule: RuleExplanation; compact?: boolean }) {
  const api = useApi();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<{ rules: RuleJustification[] } | { error: string } | "loading" | null>(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && (state === null || (typeof state === "object" && "error" in state))) {
      setState("loading");
      Promise.all(rule.keys.map((key) => loadRule(api, key)))
        .then((rules) => setState({ rules }))
        .catch((err) => setState({ error: errorMessage(err) }));
    }
  };

  return (
    <div className="rule" data-compact={compact || undefined}>
      <p className="rule-text">
        {!compact && <strong className="rule-title">{rule.title}.</strong>} {rule.text}
      </p>
      <button type="button" className="rule-toggle" aria-expanded={open} aria-controls={id} onClick={toggle}>
        <Icon name="source" size={14} />
        Sources
        <Icon name={open ? "up" : "down"} size={12} />
      </button>
      {open && (
        <div id={id} className="rule-sources">
          {state === "loading" && <p className="label scanline loading-line">Reading the rule’s sources</p>}
          {state && typeof state === "object" && "error" in state && <p className="error-text">Couldn’t load the sources: {state.error}</p>}
          {state && typeof state === "object" && "rules" in state && <RuleDetail rules={state.rules} secondHeading={rule.secondHeading} />}
        </div>
      )}
    </div>
  );
}

export function RuleDetail({ rules, secondHeading, firstHeading }: { rules: RuleJustification[]; secondHeading?: string; firstHeading?: string }) {
  const [first, second] = rules;
  return (
    <div className="rule-detail">
      {first && (
        <section>
          <h4 className="rule-claim">{firstHeading ?? first.claim}</h4>
          {firstHeading && <p className="rule-claim-text">{first.claim}</p>}
          {first.grounding_note && <Caveat text={first.grounding_note} />}
          <StudyList citations={first.supporting_citations} />
        </section>
      )}
      {second && (
        <section>
          <h4 className="rule-claim">{secondHeading ?? second.claim}</h4>
          {secondHeading && <p className="rule-claim-text">{second.claim}</p>}
          {second.grounding_note && <Caveat text={second.grounding_note} />}
          <StudyList citations={second.supporting_citations} />
        </section>
      )}
    </div>
  );
}

export function Caveat({ text, mark = "Note" }: { text: string; mark?: string }) {
  return (
    <p className="caveat">
      <span className="caveat-mark">
        <Icon name="note" size={11} />
        {mark}
      </span>
      <span>{text}</span>
    </p>
  );
}
