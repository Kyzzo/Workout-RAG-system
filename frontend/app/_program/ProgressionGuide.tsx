"use client";

import { useState } from "react";
import { DOUBLE_PROGRESSION_EVIDENCE, DOUBLE_PROGRESSION_STEPS } from "../_lib/research";
import { RuleSources } from "../_sources/RuleSources";
import { Icon } from "../_ui/Icon";

// Hypertrophy numbers stay the same week to week; the lifter progresses
// session to session. This is how.
export function ProgressionGuide() {
  const [open, setOpen] = useState(false);
  return (
    <section className="guide slab" aria-labelledby="guide-title">
      <button type="button" className="guide-toggle" aria-expanded={open} aria-controls="guide-body" onClick={() => setOpen((o) => !o)}>
        <span className="label">Double progression</span>
        <span id="guide-title" className="display guide-title">
          How to progress
        </span>
        <Icon name={open ? "up" : "down"} size={16} />
      </button>
      {open && (
        <div id="guide-body" className="guide-body">
          <ol className="guide-steps">
            {DOUBLE_PROGRESSION_STEPS.map((step, i) => (
              <li key={step.lead}>
                <span className="guide-n painted" aria-hidden>
                  {i + 1}
                </span>
                <p>
                  <strong>{step.lead}</strong> {step.rest}
                </p>
              </li>
            ))}
          </ol>
          <RuleSources rule={DOUBLE_PROGRESSION_EVIDENCE} />
        </div>
      )}
    </section>
  );
}
