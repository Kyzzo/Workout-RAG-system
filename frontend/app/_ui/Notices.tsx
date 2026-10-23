"use client";

import { useEffect, useState } from "react";
import { useApp, type Notice } from "../_state/app";
import { errorMessage } from "../useApi";
import { Icon } from "./Icon";

// Results and errors from program actions, pinned above the rail. Errors
// and anything with an action stay until dismissed.
export function Notices() {
  const { notices, dismiss, busy } = useApp();
  return (
    <div className="notices">
      <div role="status" aria-live="polite" className="notices-live" style={{ display: "contents" }}>
        {busy && (
          <div className="notice notice-working" data-tone="info">
            <span className="notice-kind scanline">Working</span>
            <span className="notice-text">
              {busy.working} <span className="quiet">Generation can take a little while.</span>
            </span>
          </div>
        )}
        {notices
          .filter((n) => n.tone !== "error")
          .map((n) => (
            <NoticeView key={n.id} notice={n} onDismiss={dismiss} />
          ))}
      </div>
      <div role="alert" style={{ display: "contents" }}>
        {notices
          .filter((n) => n.tone === "error")
          .map((n) => (
            <NoticeView key={n.id} notice={n} onDismiss={dismiss} />
          ))}
      </div>
    </div>
  );
}

function NoticeView({ notice, onDismiss }: { notice: Notice; onDismiss: (id: string) => void }) {
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const lingering = notice.tone === "done" && !notice.action;

  useEffect(() => {
    if (!lingering) return;
    const t = window.setTimeout(() => onDismiss(notice.id), 14000);
    return () => window.clearTimeout(t);
  }, [lingering, onDismiss, notice.id]);

  return (
    <div className="notice" data-tone={notice.tone}>
      <span className="notice-kind">{notice.tone === "error" ? "Error" : notice.tone === "done" ? "Done" : "Note"}</span>
      <div className="notice-text">
        {notice.text}
        {notice.lines && notice.lines.length > 0 && (
          <ul className="notice-lines">
            {notice.lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}
        {failure && <p className="error-text">{failure}</p>}
      </div>
      <div className="notice-actions">
        {notice.action && (
          <button
            type="button"
            className="btn btn-small"
            disabled={working}
            onClick={async () => {
              setWorking(true);
              setFailure(null);
              try {
                await notice.action!.run();
                onDismiss(notice.id);
              } catch (err) {
                setFailure(errorMessage(err));
                setWorking(false);
              }
            }}
          >
            {working ? "Working..." : notice.action.label}
          </button>
        )}
        <button type="button" className="btn btn-quiet btn-icon btn-small" aria-label="Dismiss" onClick={() => onDismiss(notice.id)}>
          <Icon name="close" size={14} />
        </button>
      </div>
    </div>
  );
}
