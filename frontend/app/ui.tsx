"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Alert, Check, Info, More } from "./Icons";

// Shared building blocks. Styling lives in globals.css (.btn, .card,
// .input, .chip...) so these stay thin.

export function Spinner({ className = "size-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className={`${className} animate-spin`}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

type Tone = "success" | "error" | "warn" | "info";

const NOTICE_TONE: Record<Tone, string> = {
  success: "bg-evidence-soft text-evidence",
  error: "bg-danger-soft text-danger",
  warn: "bg-warn-soft text-warn",
  info: "bg-accent-soft text-accent-text",
};

const NOTICE_ICON: Record<Tone, React.ReactNode> = {
  success: <Check className="size-4" />,
  error: <Alert className="size-4" />,
  warn: <Alert className="size-4" />,
  info: <Info className="size-4" />,
};

// An inline status line: an icon carries the meaning as well as the colour.
export function Notice({
  tone,
  children,
  action,
  className = "",
}: {
  tone: Tone;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`animate-in flex items-start gap-2.5 rounded-xl px-3.5 py-2.5 text-sm ${NOTICE_TONE[tone]} ${className}`}
    >
      <span className="mt-0.5 shrink-0">{NOTICE_ICON[tone]}</span>
      <div className="min-w-0 flex-1 whitespace-pre-line leading-relaxed">{children}</div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export type MenuItem = {
  label: string;
  icon?: React.ReactNode;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
};

// An overflow menu: always visible (no hover-only actions), closes on
// selection, outside click or Escape, and returns focus to its button.
export function Menu({
  label,
  items,
  disabled,
  quiet = false,
}: {
  label: string;
  items: MenuItem[];
  disabled?: boolean;
  // Lower emphasis when repeated on every row (still always visible).
  quiet?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Arrow keys move between items, as in a native menu.
  function onMenuKey(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? at + 1 : at - 1;
    buttons[(next + buttons.length) % buttons.length]?.focus();
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={`icon-btn ${quiet ? "opacity-55 hover:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100" : ""}`}
      >
        <More className="size-4" />
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          onKeyDown={onMenuKey}
          className="animate-pop absolute end-0 top-full z-30 mt-1.5 min-w-52 rounded-xl border border-line-strong bg-surface p-1 shadow-pop"
        >
          {items.map((item, i) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              autoFocus={i === 0}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-start text-sm outline-none disabled:opacity-40 ${
                item.danger
                  ? "text-danger hover:bg-danger-soft focus-visible:bg-danger-soft"
                  : "text-fg hover:bg-surface-2 focus-visible:bg-surface-2"
              }`}
            >
              {item.icon && <span className={item.danger ? "" : "text-fg-subtle"}>{item.icon}</span>}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: React.ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-fg">
          {label}
        </label>
        {description && <div className="mt-0.5 text-sm text-fg-muted leading-relaxed">{description}</div>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-6 w-10 shrink-0 items-center rounded-full border transition-colors duration-150 disabled:opacity-50 ${
          checked ? "border-transparent bg-accent" : "border-line-control bg-surface-3"
        }`}
      >
        <span
          className={`size-[18px] rounded-full bg-white shadow-sm transition-transform duration-200 ease-[var(--ease-out)] ${
            checked ? "translate-x-[18px]" : "translate-x-[2px]"
          }`}
        />
      </button>
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="grid auto-cols-fr grid-flow-col gap-1 rounded-xl bg-surface-2 p-1 border border-line">
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={`h-8 rounded-lg text-sm font-medium transition-[background-color,color,box-shadow] duration-150 disabled:opacity-50 ${
              selected ? "bg-surface text-fg shadow-card ring-1 ring-line-strong" : "text-fg-muted hover:text-fg"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex min-w-0 flex-col gap-1.5 ${className}`}>
      <span className="text-[13px] font-medium text-fg-muted">{label}</span>
      {children}
      {hint && <span className="text-xs text-fg-subtle">{hint}</span>}
    </label>
  );
}

export function ProgressBar({ value }: { value: number | null }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value === null ? undefined : Math.round(value * 100)}>
      {value === null ? (
        <div className="h-full w-1/3 animate-[indeterminate_1.2s_var(--ease-in-out)_infinite] rounded-full bg-accent" />
      ) : (
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-[var(--ease-out)]"
          style={{ width: `${Math.max(4, value * 100)}%` }}
        />
      )}
    </div>
  );
}

// Pulsing placeholder lines while a program loads.
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-3/70 ${className}`} />;
}
