"use client";

import { useEffect, useRef, type ReactNode } from "react";

// A side panel on wide screens, the whole screen on phones. Native modal
// <dialog>: the page behind goes inert, Tab stays inside, Escape closes, and
// focus returns to whatever opened it.
export function Sheet({
  open,
  onClose,
  labelledBy,
  className,
  children,
}: {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={className ? `sheet ${className}` : "sheet"}
      aria-labelledby={labelledBy}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onClose={() => open && onClose()}
    >
      <div className="sheet-frame">{children}</div>
    </dialog>
  );
}
