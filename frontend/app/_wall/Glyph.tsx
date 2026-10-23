import type { DisplayStatus } from "../_lib/tracker/schedule";

export const STATUS_TEXT: Record<DisplayStatus, string> = {
  completed: "Completed",
  partial: "Partial",
  skipped: "Skipped",
  missed: "Missed",
  scheduled: "Scheduled",
};

// Session status as a shape, so it reads without colour: an empty frame
// (to come), solid with a notch (done), half-filled (partial), struck
// through (skipped), hatched (missed).
export function StatusGlyph({ status, size = 12 }: { status: DisplayStatus; size?: number }) {
  return (
    <svg className="glyph" data-status={status} width={size} height={size} viewBox="0 0 12 12" aria-hidden focusable="false">
      {status === "completed" ? (
        <>
          <rect x="0.75" y="0.75" width="10.5" height="10.5" fill="currentColor" />
          <path d="M3.2 6.3l1.9 1.9 3.8-4.2" fill="none" stroke="var(--glyph-cut, #111)" strokeWidth="1.6" strokeLinecap="square" />
        </>
      ) : (
        <>
          <rect x="1.25" y="1.25" width="9.5" height="9.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          {status === "partial" && <path d="M1.25 1.25v9.5h9.5z" fill="currentColor" />}
          {status === "skipped" && <path d="M1.5 10.5L10.5 1.5" stroke="currentColor" strokeWidth="1.5" />}
          {status === "missed" && (
            <path d="M1.5 5.5l4-4M1.5 9.5l8-8M5.5 10.5l5-5" stroke="currentColor" strokeWidth="1" />
          )}
        </>
      )}
    </svg>
  );
}
