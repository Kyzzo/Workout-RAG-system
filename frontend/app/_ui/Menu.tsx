"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export type MenuItem =
  | {
      label: string;
      icon?: IconName;
      onSelect: () => void;
      disabled?: boolean;
      danger?: boolean;
    }
  | "sep"
  | { note: ReactNode };

// A menu button: arrow keys move, Home/End jump, Escape closes and puts focus
// back on the button, a click outside or Tab away closes it.
export function Menu({
  label,
  items,
  icon = "more",
  text,
  align = "right",
  up = false,
  disabled = false,
  className = "btn btn-quiet btn-icon btn-small",
}: {
  label: string;
  items: MenuItem[];
  icon?: IconName;
  text?: string;
  align?: "left" | "right";
  up?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();

  const enabled = () => [...(list.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not(:disabled)") ?? [])];

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLButtonElement>("[role=menuitem]:not(:disabled)")?.focus();
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const items = enabled();
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      items[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      items[items.length - 1]?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  return (
    <div className="menu-wrap" ref={wrap}>
      <button
        ref={button}
        type="button"
        className={className}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={text ? undefined : label}
        title={text ? undefined : label}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Icon name={icon} size={16} />
        {text && <span>{text}</span>}
      </button>
      {open && (
        <div
          ref={list}
          id={id}
          role="menu"
          aria-label={label}
          className="menu"
          data-align={align}
          data-up={up || undefined}
          onKeyDown={onKeyDown}
        >
          {items.map((item, i) => {
            if (item === "sep") return <div key={`sep${i}`} className="menu-sep" role="separator" />;
            if ("note" in item)
              return (
                <div key={`note${i}`} className="menu-note label">
                  {item.note}
                </div>
              );
            return (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className="menu-item"
                data-danger={item.danger || undefined}
                disabled={item.disabled}
                onClick={() => {
                  close(true);
                  item.onSelect();
                }}
              >
                {item.icon && <Icon name={item.icon} size={16} />}
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
