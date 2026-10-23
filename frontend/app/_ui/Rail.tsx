"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApp } from "../_state/app";
import { useSession } from "../_state/session";
import { useUi } from "../_state/ui";
import { Icon } from "./Icon";

// The bottom rail: two views (the wall, the program) and two tools kept out
// of the way (ask, new program).
export function Rail() {
  const pathname = usePathname();
  const { sheet, openChat, openNew, closeSheet } = useUi();
  const { run } = useApp();
  const { status, account, openSignIn } = useSession();
  const pos = pathname === "/" ? "0" : pathname.startsWith("/program") ? "1" : "none";
  const generating = !!run && !run.result;

  return (
    <nav className="rail" aria-label="Main">
      <div className="rail-inner">
        <div className="rail-views">
          <span className="rail-plate" data-pos={pos} aria-hidden />
          <Link href="/" className="rail-item" aria-current={pos === "0" ? "page" : undefined} onClick={closeSheet}>
            <Icon name="wall" size={20} />
            <span>Schedule</span>
          </Link>
          <Link href="/program" className="rail-item" aria-current={pos === "1" ? "page" : undefined} onClick={closeSheet}>
            <Icon name="plan" size={20} />
            <span>Program</span>
          </Link>
        </div>
        <span className="rail-gap" aria-hidden />
        <button
          type="button"
          className="rail-item"
          aria-haspopup="dialog"
          aria-expanded={sheet === "chat"}
          onClick={() => (sheet === "chat" ? closeSheet() : openChat(true))}
        >
          <Icon name="ask" size={20} />
          <span>Ask</span>
        </button>
        <button
          type="button"
          className="rail-item"
          aria-haspopup="dialog"
          aria-expanded={sheet === "new"}
          disabled={generating}
          title={generating ? "A program is generating" : undefined}
          onClick={() => (sheet === "new" ? closeSheet() : openNew())}
        >
          <Icon name="plus" size={20} />
          <span>New</span>
        </button>
        <span className="rail-account">
          {status === "user" ? (
            account
          ) : status === "guest" ? (
            <button type="button" className="rail-signin" onClick={openSignIn}>
              Sign in
            </button>
          ) : null}
        </span>
      </div>
    </nav>
  );
}
