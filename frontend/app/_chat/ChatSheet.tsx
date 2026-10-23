"use client";

import { useEffect, useRef } from "react";
import { askPrompts, changePrompts, GENERAL_QUESTIONS } from "../_lib/chatModel";
import { useChat } from "../_state/chat";
import { useUi } from "../_state/ui";
import { Icon } from "../_ui/Icon";
import { Sheet } from "../_ui/Sheet";
import { TurnView } from "./Turns";

export function ChatSheet() {
  const { sheet, closeSheet, chatFocus } = useUi();
  const chat = useChat();
  const open = sheet === "chat";
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);

  // Focus the message box without jumping the page; on phones bring it
  // into view above the keyboard.
  useEffect(() => {
    if (!open || !chatFocus) return;
    const el = input.current;
    if (!el) return;
    el.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 899px)").matches) {
      requestAnimationFrame(() => el.scrollIntoView({ block: "end" }));
    }
  }, [open, chatFocus]);

  // Keep the newest message in view.
  const count = chat.turns.length;
  useEffect(() => {
    const el = log.current;
    if (!el || !open) return;
    el.scrollTo({ top: el.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [count, chat.sending, chat.stage, open]);

  return (
    <Sheet open={open} onClose={closeSheet} labelledBy="chat-title" className="sheet-chat">
      <header className="sheet-head chat-head">
        <div>
          <p className="label">Ask</p>
          <h2 id="chat-title" className="sheet-title display">
            Evidence desk
          </h2>
        </div>
        <div className="chat-head-tools">
          {chat.turns.length > 0 && (
            <button type="button" className="btn btn-quiet btn-small" onClick={() => void chat.clearHistory()} disabled={chat.sending}>
              <Icon name="trash" size={14} />
              <span className="hide-narrow">Clear history</span>
              <span className="sr-only">Clear history</span>
            </button>
          )}
          <button type="button" className="btn btn-quiet btn-icon" aria-label="Close" onClick={closeSheet}>
            <Icon name="close" />
          </button>
        </div>
      </header>

      {chat.anchor && (
        <div className="chat-anchor">
          <span className="label">About</span>
          <span className="chat-anchor-name">{chat.anchor.label}</span>
          {chat.anchor.thisWeekOnly && <span className="tag">This week only</span>}
          <button type="button" className="btn btn-quiet btn-icon btn-small" aria-label="Stop asking about this" onClick={chat.clearAnchor}>
            <Icon name="close" size={14} />
          </button>
        </div>
      )}

      <div ref={log} className="chat-log" aria-live="polite" aria-relevant="additions">
        {chat.historyError && <p className="field-hint chat-history-error">Couldn’t load your saved conversation, so this starts empty.</p>}
        {chat.turns.length === 0 && !chat.sending && <ChatIntro />}
        {chat.turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} />
        ))}
        {chat.sending && (
          <div className="turn turn-wait" role="status">
            <span className="turn-who label">Desk</span>
            <div className="turn-body">
              <p className="chat-stage">
                <span className="chat-stage-text" key={chat.stage ?? "start"}>
                  {chat.stage ?? "Reading the research..."}
                </span>
              </p>
              <span className="chat-reading scanline" aria-hidden />
            </div>
          </div>
        )}
      </div>

      <Prompts />
      <Composer inputRef={input} />
    </Sheet>
  );
}

function ChatIntro() {
  return (
    <div className="chat-intro">
      <p className="chat-intro-big serif-i">Ask what the research says.</p>
      <p className="chat-intro-text">
        Answers come with numbered citations, each checked against its study. Open any value’s <b>Ask</b> to question it
        or change it; changes can be undone.
      </p>
    </div>
  );
}

function Prompts() {
  const chat = useChat();
  const disabled = chat.sending;
  if (chat.anchor) {
    return (
      <div className="prompts" aria-label="Suggestions">
        <div className="prompt-group" role="group" aria-label="Ask">
          <span className="label prompt-kind">Ask</span>
          {askPrompts(chat.loadIsPercent).map((p) => (
            <button key={p} type="button" className="prompt" disabled={disabled} onClick={() => void chat.send(p)}>
              {p}
            </button>
          ))}
        </div>
        <div className="prompt-group" role="group" aria-label="Change">
          <span className="label prompt-kind">Change</span>
          {changePrompts(chat.loadIsPercent).map((p) => (
            <button key={p} type="button" className="prompt prompt-change" disabled={disabled} onClick={() => void chat.send(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="prompts" aria-label="Suggestions">
      <div className="prompt-group" role="group" aria-label={`${chat.goal} questions`}>
        <span className="label prompt-kind">{chat.goal === "strength" ? "Strength" : "Hypertrophy"}</span>
        {GENERAL_QUESTIONS[chat.goal].map((q) => (
          <button key={q} type="button" className="prompt" disabled={disabled} onClick={() => void chat.send(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function Composer({ inputRef }: { inputRef: React.RefObject<HTMLTextAreaElement | null> }) {
  const chat = useChat();
  const submit = () => {
    if (!chat.composer.trim() || chat.sending) return;
    void chat.send(chat.composer);
  };
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label className="sr-only" htmlFor="chat-input">
        Message
      </label>
      <textarea
        id="chat-input"
        ref={inputRef}
        className="textarea composer-input"
        rows={1}
        value={chat.composer}
        placeholder={chat.anchor ? `Ask about ${chat.anchor.label}, or ask for a change` : "Ask about sets, reps, effort, frequency..."}
        onChange={(e) => chat.setComposer(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends, Shift+Enter breaks the line, nothing while an IME composes.
          if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return;
          e.preventDefault();
          submit();
        }}
      />
      <button type="submit" className="btn btn-steel btn-icon composer-send" aria-label="Send" disabled={chat.sending || !chat.composer.trim()}>
        <Icon name="send" />
      </button>
    </form>
  );
}

// What a signed-out visitor sees: the desk at rest.
export function ChatPreview() {
  return (
    <div className="chat-preview">
      <p className="label">Evidence desk</p>
      <ChatIntro />
      <div className="prompts prompts-static">
        <div className="prompt-group">
          <span className="label prompt-kind">Hypertrophy</span>
          {GENERAL_QUESTIONS.hypertrophy.map((q) => (
            <button key={q} type="button" className="prompt">
              {q}
            </button>
          ))}
        </div>
      </div>
      <div className="composer composer-static">
        <textarea className="textarea composer-input" rows={1} placeholder="Ask about sets, reps, effort, frequency..." readOnly aria-label="Message" />
        <button type="button" className="btn btn-steel btn-icon composer-send" aria-label="Send">
          <Icon name="send" />
        </button>
      </div>
    </div>
  );
}
