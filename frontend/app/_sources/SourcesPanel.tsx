"use client";

import { useEffect, useState } from "react";
import { loadRule, loadSummary, summaryIds, type SourcesRequest } from "../_lib/evidence";
import { SPLIT_RULE_HEADING, SPLIT_RULE_KEY } from "../_lib/research";
import { useApi } from "../_state/session";
import { useSources } from "../_state/sources";
import { Icon } from "../_ui/Icon";
import { Sheet } from "../_ui/Sheet";
import type { RuleJustification } from "../types";
import { errorMessage } from "../useApi";
import { Caveat, RuleDetail } from "./RuleSources";
import { StudyList } from "./StudyList";

export function SourcesPanel() {
  const { request, closeSources } = useSources();
  return (
    <Sheet open={!!request} onClose={closeSources} labelledBy="src-title" className="sheet-src">
      {request && <SourcesBody key={`${request.heading}|${request.question}`} request={request} onClose={closeSources} />}
    </Sheet>
  );
}

type Summary = { value: string | null } | { error: string } | null;

function SourcesBody({ request, onClose }: { request: SourcesRequest; onClose: () => void }) {
  const api = useApi();
  const ids = summaryIds(request.citations);
  const asks = !!request.question && ids.length > 0;
  const [summary, setSummary] = useState<Summary>(null);
  const [rule, setRule] = useState<RuleJustification | "failed" | null>(null);

  useEffect(() => {
    if (!request.question || !request.citations.length) return;
    let alive = true;
    loadSummary(api, request.question, summaryIds(request.citations))
      .then((value) => alive && setSummary({ value }))
      .catch((err) => alive && setSummary({ error: errorMessage(err) }));
    return () => {
      alive = false;
    };
  }, [api, request]);

  useEffect(() => {
    if (!request.splitRule) return;
    let alive = true;
    loadRule(api, SPLIT_RULE_KEY)
      .then((r) => alive && setRule(r))
      .catch(() => alive && setRule("failed"));
    return () => {
      alive = false;
    };
  }, [api, request]);

  return (
    <>
      <header className="sheet-head">
        <div>
          <p className="label">Evidence</p>
          <h2 id="src-title" className="sheet-title display src-heading">
            {request.heading}
          </h2>
        </div>
        <button type="button" className="btn btn-quiet btn-icon" aria-label="Close sources" onClick={onClose}>
          <Icon name="close" />
        </button>
      </header>
      <div className="sheet-scroll src">
        {asks && (
          <section className="src-summary" aria-live="polite" aria-busy={summary === null}>
            {summary === null && (
              <div className="src-reading">
                <span className="label">
                  Summarising {ids.length} {ids.length === 1 ? "study" : "studies"}...
                </span>
                <span className="src-lines scanline" aria-hidden>
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            )}
            {summary && "value" in summary && summary.value && <p className="src-summary-text">{summary.value}</p>}
            {summary && "error" in summary && <p className="error-text">Couldn’t summarise these studies: {summary.error}</p>}
          </section>
        )}

        {request.note && <Caveat text={request.note} />}

        {request.citations.length > 0 ? (
          <section className="src-studies">
            <h3 className="label src-sub">
              Verified studies <span className="src-count">{new Set(request.citations.map((c) => c.citation.id)).size} excerpts</span>
            </h3>
            <StudyList citations={request.citations} />
          </section>
        ) : (
          <p className="src-none">No verified source supports this value directly. The note above explains where it comes from.</p>
        )}

        {request.splitRule && (
          <section className="src-rule">
            <h3 className="label src-sub">The rule behind the split</h3>
            {rule === null && <p className="label scanline loading-line">Reading the rule</p>}
            {rule === "failed" && <p className="field-hint">The rule’s sources couldn’t be loaded right now.</p>}
            {rule && rule !== "failed" && <RuleDetail rules={[rule]} firstHeading={SPLIT_RULE_HEADING} />}
          </section>
        )}
      </div>
    </>
  );
}
