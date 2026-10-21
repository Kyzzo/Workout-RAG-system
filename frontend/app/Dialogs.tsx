"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Alert } from "./Icons";

// In-app replacements for window.confirm / window.prompt: same promise
// shape (confirm -> boolean, prompt -> string | null), but styled, with
// room for a list of consequences, and a red button for destructive ones.
// Built on <dialog>, which brings focus trapping, Escape and the backdrop.

type ConfirmOptions = {
  title: string;
  body?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

type PromptOptions = {
  title: string;
  body?: React.ReactNode;
  label: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  // Allow submitting an empty value (e.g. "leave blank for a suggestion").
  allowEmpty?: boolean;
};

type Request = { id: number } & (
  | ({ kind: "confirm"; resolve: (ok: boolean) => void } & ConfirmOptions)
  | ({ kind: "prompt"; resolve: (value: string | null) => void } & PromptOptions)
);

type Dialogs = {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  prompt: (options: PromptOptions) => Promise<string | null>;
};

const DialogContext = createContext<Dialogs | null>(null);

export function useDialogs(): Dialogs {
  const dialogs = useContext(DialogContext);
  if (!dialogs) throw new Error("useDialogs needs a <DialogProvider> above it");
  return dialogs;
}

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const [request, setRequest] = useState<Request | null>(null);
  const nextId = useRef(0);

  const confirm = useCallback(
    (options: ConfirmOptions) => new Promise<boolean>((resolve) => setRequest({ id: ++nextId.current, kind: "confirm", resolve, ...options })),
    [],
  );
  const prompt = useCallback(
    (options: PromptOptions) =>
      new Promise<string | null>((resolve) => setRequest({ id: ++nextId.current, kind: "prompt", resolve, ...options })),
    [],
  );

  return (
    <DialogContext.Provider value={{ confirm, prompt }}>
      {children}
      {request && <DialogView key={request.id} request={request} onDone={() => setRequest(null)} />}
    </DialogContext.Provider>
  );
}

function DialogView({ request, onDone }: { request: Request; onDone: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState(request.kind === "prompt" ? (request.defaultValue ?? "") : "");
  const settled = useRef(false);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  function finish(ok: boolean) {
    if (settled.current) return;
    settled.current = true;
    if (request.kind === "confirm") request.resolve(ok);
    else request.resolve(ok ? value : null);
    ref.current?.close();
    onDone();
  }

  const canSubmit = request.kind === "confirm" || request.allowEmpty || value.trim() !== "";
  const danger = request.kind === "confirm" && request.danger;

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        finish(false);
      }}
      onClick={(e) => {
        // A click on the backdrop (the dialog element itself) cancels.
        if (e.target === ref.current) finish(false);
      }}
    >
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) finish(true);
        }}
        className="flex flex-col"
      >
        <div className="flex gap-3.5 px-5 pt-5">
          {danger && (
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-danger-soft text-danger">
              <Alert className="size-[18px]" />
            </span>
          )}
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <h2 id="dialog-title" className="sign-type text-base">
              {request.title}
            </h2>
            {request.body && <div className="text-sm leading-relaxed text-fg-muted">{request.body}</div>}
            {request.kind === "prompt" && (
              <label className="mt-1 flex flex-col gap-1.5">
                <span className="text-[13px] font-medium text-fg-muted">{request.label}</span>
                <input
                  autoFocus
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  placeholder={request.placeholder}
                  className="input"
                />
              </label>
            )}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2 border-t border-line bg-surface-2/60 px-5 py-3.5 rounded-b-2xl">
          <button type="button" onClick={() => finish(false)} className="btn btn-ghost" autoFocus={request.kind === "confirm"}>
            {(request.kind === "confirm" && request.cancelLabel) || "Cancel"}
          </button>
          <button type="submit" disabled={!canSubmit} className={`btn ${danger ? "btn-danger" : "btn-primary"}`}>
            {request.confirmLabel ?? (request.kind === "prompt" ? "Save" : "Confirm")}
          </button>
        </div>
      </form>
    </dialog>
  );
}
