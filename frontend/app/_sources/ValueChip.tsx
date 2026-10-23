"use client";

import { FIELD_NAMES, sourcesState, type SourcesRequest, type ValueField } from "../_lib/evidence";
import { useSources } from "../_state/sources";

// A prescribed value with its evidence: a count of verified sources, a
// "see the note" mark when there's only a caveat, or nothing at all.
export function ValueChip({
  text,
  field,
  request,
  direction,
  previous,
}: {
  text: string;
  field: ValueField;
  request: SourcesRequest | null;
  direction?: "up" | "down" | null;
  previous?: string;
}) {
  const { openSources } = useSources();
  const state = sourcesState(request);
  const arrow = direction ? (
    <span className="vchip-dir" data-dir={direction} title={previous ? `Week before: ${previous}` : undefined}>
      <span aria-hidden>{direction === "up" ? "▲" : "▼"}</span>
      <span className="sr-only">
        {direction === "up" ? "up" : "down"} from {previous}
      </span>
    </span>
  ) : null;

  if (state.kind === "none" || !request) {
    return (
      <span className="vchip" data-field={field}>
        <span className="vchip-text">{text}</span>
        {arrow}
      </span>
    );
  }
  const name = FIELD_NAMES[field];
  const label =
    state.kind === "cited"
      ? `${text}: show ${state.count} verified source${state.count === 1 ? "" : "s"} for ${name}`
      : `${text}: no verified source for ${name} - see the note`;
  return (
    <button type="button" className="vchip" data-field={field} data-kind={state.kind} aria-label={label} onClick={() => openSources(request)}>
      <span className="vchip-text">{text}</span>
      {arrow}
      {state.kind === "cited" ? (
        <span className="vchip-count" aria-hidden>
          {state.count}
        </span>
      ) : (
        <span className="vchip-note" aria-hidden>
          ※
        </span>
      )}
    </button>
  );
}
