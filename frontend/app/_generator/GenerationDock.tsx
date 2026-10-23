"use client";

import { useApp } from "../_state/app";
import { Icon } from "../_ui/Icon";

// Generation in progress, docked above the rail so the program can be
// watched filling in. It can't be dismissed until the run ends.
export function GenerationDock() {
  const { run, stopRun, dismissRun } = useApp();
  if (!run) return null;
  const result = run.result;
  const current = run.phases.indexOf(run.phase);
  const fraction = run.total ? run.done / run.total : 0;
  const label =
    run.phase === "Choosing exercises" ? "Choosing exercises for each day" : `${run.phase} ${run.done}/${run.total ?? "?"}`;

  return (
    <section className="dock" aria-label="Generation" data-done={result ? "" : undefined}>
      <div className="dock-inner">
        <div className="dock-head">
          <span className="dock-kind label">
            {result ? (result.ok ? "Finished" : "Ended") : run.stopping ? "Stopping" : "Generating"}
          </span>
          <span className="dock-title">{run.title}</span>
          {result ? (
            <button type="button" className="btn btn-small" onClick={dismissRun}>
              Close
            </button>
          ) : (
            <button type="button" className="btn btn-small" onClick={stopRun} disabled={run.stopping}>
              <Icon name="stop" size={12} />
              {run.stopping ? "Stopping..." : "Stop"}
            </button>
          )}
        </div>

        {result ? (
          <div className="dock-result" role="status">
            <p>{result.message}</p>
            {result.failures.length > 0 && (
              <ul className="notice-lines">
                <li>
                  {result.failures.length} step{result.failures.length === 1 ? "" : "s"} failed:
                </li>
                {result.failures.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <>
            <p className="dock-phase" role="status" aria-live="polite">
              {label}
            </p>
            <div className="dock-track" aria-hidden data-indeterminate={!run.total || undefined}>
              <span className="dock-fill" style={{ transform: `scaleX(${run.total ? fraction : 1})` }} />
            </div>
            <ol className="dock-phases" aria-label="Steps">
              {run.phases.map((phase, i) => (
                <li key={phase} data-state={i < current ? "done" : i === current ? "now" : "next"}>
                  <span className="dock-pip" aria-hidden />
                  {phase}
                  <span className="sr-only">{i < current ? ", done" : i === current ? ", in progress" : ", to come"}</span>
                </li>
              ))}
            </ol>
            <p className="dock-note">Keep this tab open until it finishes. Stopping keeps the steps already done.</p>
          </>
        )}
      </div>
    </section>
  );
}
