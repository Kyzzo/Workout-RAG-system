import Link from "next/link";
import type { ReactNode } from "react";

export function Masthead({ title, children }: { title?: ReactNode; children?: ReactNode }) {
  return (
    <header className="masthead">
      <div className="masthead-mark">
        <Link href="/" className="masthead-home" aria-label="Citeset: schedule">
          <span className="tiehole" aria-hidden />
          <span className="wordmark steel-text">Citeset</span>
        </Link>
        {title && <span className="masthead-sub label">{title}</span>}
      </div>
      {children && <div className="masthead-tools">{children}</div>}
    </header>
  );
}
