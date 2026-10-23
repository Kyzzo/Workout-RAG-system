"use client";

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "../_ui/Icon";

// In-app confirm and prompt dialogs (never window.confirm/prompt): native
// modal <dialog>, so focus stays inside and Escape cancels. confirm resolves
// to a boolean, prompt to the text or null.

export type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  consequences?: string[];
  destructive?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
};

export type PromptOptions = {
  title: string;
  body?: ReactNode;
  label: string;
  initial?: string;
  placeholder?: string;
  allowEmpty?: boolean;
  maxLength?: number;
  confirmLabel?: string;
  cancelLabel?: string;
};

type Request =
  | { id: number; kind: "confirm"; options: ConfirmOptions; resolve: (v: boolean) => void; returnTo: Element | null }
  | { id: number; kind: "prompt"; options: PromptOptions; resolve: (v: string | null) => void; returnTo: Element | null };

type DialogsValue = {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  prompt: (options: PromptOptions) => Promise<string | null>;
};

const DialogsContext = createContext<DialogsValue | null>(null);

let nextId = 1;

export function DialogsProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<Request[]>([]);

  const confirm = useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        const request: Request = { id: nextId++, kind: "confirm", options, resolve, returnTo: document.activeElement };
        setQueue((q) => [...q, request]);
      }),
    [],
  );

  const prompt = useCallback(
    (options: PromptOptions) =>
      new Promise<string | null>((resolve) => {
        const request: Request = { id: nextId++, kind: "prompt", options, resolve, returnTo: document.activeElement };
        setQueue((q) => [...q, request]);
      }),
    [],
  );

  const value = useMemo(() => ({ confirm, prompt }), [confirm, prompt]);
  const current = queue[0] ?? null;

  const finish = useCallback((request: Request, result: boolean | string | null) => {
    if (request.kind === "confirm") request.resolve(result === true);
    else request.resolve(typeof result === "string" ? result : null);
    setQueue((q) => q.filter((r) => r.id !== request.id));
    // Closing the native dialog already restores focus; this covers an opener
    // that was re-rendered meanwhile.
    const back = request.returnTo;
    window.setTimeout(() => {
      const lost = !document.activeElement || document.activeElement === document.body;
      if (lost && back instanceof HTMLElement && back.isConnected) back.focus({ preventScroll: true });
    }, 0);
  }, []);

  return (
    <DialogsContext value={value}>
      {children}
      {current && <DialogView key={current.id} request={current} onDone={finish} />}
    </DialogsContext>
  );
}

export function useDialogs(): DialogsValue {
  const value = useContext(DialogsContext);
  if (!value) throw new Error("useDialogs outside DialogsProvider");
  return value;
}

function DialogView({ request, onDone }: { request: Request; onDone: (r: Request, v: boolean | string | null) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const isPrompt = request.kind === "prompt";
  const options = request.options;
  const destructive = request.kind === "confirm" && !!request.options.destructive;
  const [text, setText] = useState(isPrompt ? (request.options.initial ?? "") : "");

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    // Destructive: start on the safe choice. Prompts: in the field.
    if (isPrompt) {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else if (destructive) cancelRef.current?.focus();
    else confirmRef.current?.focus();
  }, [isPrompt, destructive]);

  const cancelValue = isPrompt ? null : false;
  const done = (value: boolean | string | null) => {
    ref.current?.close();
    onDone(request, value);
  };
  const canSubmit = !isPrompt || (request.kind === "prompt" && (request.options.allowEmpty || text.trim().length > 0));

  return (
    <dialog
      ref={ref}
      className="dlg"
      data-destructive={destructive || undefined}
      aria-labelledby={titleId}
      aria-describedby={options.body || (request.kind === "confirm" && request.options.consequences) ? bodyId : undefined}
      onCancel={(e) => {
        e.preventDefault();
        done(cancelValue);
      }}
    >
      <form
        className="dlg-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          done(isPrompt ? text : true);
        }}
      >
        <header className="dlg-head">
          {destructive && (
            <span className="dlg-flag">
              <Icon name="warning" /> Destructive
            </span>
          )}
          <h2 id={titleId} className="dlg-title">
            {options.title}
          </h2>
        </header>
        <div id={bodyId} className="dlg-body">
          {options.body}
          {request.kind === "confirm" && request.options.consequences && request.options.consequences.length > 0 && (
            <ul className="dlg-list">
              {request.options.consequences.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </div>
        {request.kind === "prompt" && (
          <label className="field">
            <span className="field-label">{request.options.label}</span>
            <input
              ref={inputRef}
              className="input"
              value={text}
              maxLength={request.options.maxLength}
              placeholder={request.options.placeholder}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
        )}
        <div className="dlg-actions">
          <button ref={cancelRef} type="button" className="btn btn-quiet" onClick={() => done(cancelValue)}>
            {options.cancelLabel ?? "Cancel"}
          </button>
          <button
            ref={confirmRef}
            type="submit"
            className={destructive ? "btn btn-danger" : "btn btn-steel"}
            disabled={!canSubmit}
          >
            {options.confirmLabel ?? (isPrompt ? "Save" : "Confirm")}
          </button>
        </div>
      </form>
    </dialog>
  );
}
