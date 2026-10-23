"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { ChatSheet } from "../_chat/ChatSheet";
import { GenerationDock } from "../_generator/GenerationDock";
import { GeneratorSheet } from "../_generator/GeneratorSheet";
import { SourcesPanel } from "../_sources/SourcesPanel";
import { useApp } from "../_state/app";
import { useSession } from "../_state/session";
import { Notices } from "./Notices";
import { Rail } from "./Rail";

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { status, openSignIn } = useSession();
  const { run } = useApp();
  const root = useRef<HTMLDivElement>(null);
  const guest = status === "guest";
  const auth = pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");

  // Guests look but don't touch: any press or key (except Tab and modified
  // shortcuts) opens sign-in instead, so no control takes focus, no select
  // opens and no request fires. Sign-in opens on pointer-down only; the
  // click that follows is swallowed.
  useEffect(() => {
    const el = root.current;
    if (!el || !guest) return;
    const stop = (e: Event) => {
      e.preventDefault();
      e.stopPropagation();
    };
    const onPointerDown = (e: PointerEvent) => {
      stop(e);
      openSignIn();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
      stop(e);
      openSignIn();
    };
    el.addEventListener("pointerdown", onPointerDown, true);
    el.addEventListener("click", stop, true);
    el.addEventListener("keydown", onKeyDown, true);
    return () => {
      el.removeEventListener("pointerdown", onPointerDown, true);
      el.removeEventListener("click", stop, true);
      el.removeEventListener("keydown", onKeyDown, true);
    };
  }, [guest, openSignIn]);

  // Track the visible viewport so sheets sit above an on-screen keyboard.
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const style = document.documentElement.style;
    const update = () => {
      style.setProperty("--vvh", `${vv.height}px`);
      style.setProperty("--vvt", `${vv.offsetTop}px`);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, []);

  if (auth) return <div className="app-auth">{children}</div>;

  return (
    <div ref={root} className="app" data-docked={run ? "" : undefined} data-guest={guest || undefined}>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <main id="main" className="app-main">
        {children}
      </main>
      <Notices />
      <GenerationDock />
      <Rail />
      <ChatSheet />
      <GeneratorSheet />
      <SourcesPanel />
    </div>
  );
}
