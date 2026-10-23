"use client";

import { useEffect, useState } from "react";
import { groupStudies, loadExcerpt, VERDICT_TEXT, type Study } from "../_lib/evidence";
import { useApi } from "../_state/session";
import { Icon } from "../_ui/Icon";
import type { SupportingCitation } from "../types";

// Studies grouped by paper, the ones that state the value directly first.
// Excerpts load when a study is opened.
export function StudyList({ citations }: { citations: SupportingCitation[] }) {
  const studies = groupStudies(citations);
  if (!studies.length) return null;
  return (
    <ol className="studies">
      {studies.map((study, i) => (
        <StudyItem key={study.paper} study={study} index={i} />
      ))}
    </ol>
  );
}

function StudyItem({ study, index }: { study: Study; index: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="study" data-verdict={study.verdict} style={{ "--i": index } as React.CSSProperties}>
      <button type="button" className="study-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="study-paper">{study.paper}</span>
        <span className="study-verdict" data-verdict={study.verdict}>
          {study.verdict === "primary_support" ? <Icon name="check" size={12} /> : <Icon name="layers" size={12} />}
          {VERDICT_TEXT[study.verdict]}
        </span>
        {study.details.length > 0 && <span className="study-details">{study.details.join(" · ")}</span>}
        <span className="study-toggle" aria-hidden>
          <Icon name={open ? "up" : "down"} size={14} />
        </span>
      </button>
      {open && (
        <div className="study-excerpts">
          {study.citationIds.map((id) => (
            <Excerpt key={id} id={id} />
          ))}
        </div>
      )}
    </li>
  );
}

function Excerpt({ id }: { id: number }) {
  const api = useApi();
  const [state, setState] = useState<{ text: string } | { failed: true } | null>(null);

  useEffect(() => {
    let alive = true;
    loadExcerpt(api, id)
      .then((c) => alive && setState({ text: c.snippet }))
      .catch(() => alive && setState({ failed: true }));
    return () => {
      alive = false;
    };
  }, [api, id]);

  if (!state) return <p className="excerpt excerpt-loading scanline label">Loading the excerpt</p>;
  if ("failed" in state) return <p className="excerpt error-text">Couldn’t load this excerpt.</p>;
  return <blockquote className="excerpt">{state.text}</blockquote>;
}
