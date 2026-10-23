"use client";

import { useEffect, useRef, useState } from "react";
import { valueSources, type ValueField } from "../_lib/evidence";
import { capitalize, prettyRange } from "../_lib/format";
import {
  applyChange,
  checklistItems,
  previousAchieved,
  type ChecklistChange,
  type ChecklistItem,
} from "../_lib/tracker/checklist";
import { dayOfMonth, isValidISO, MONTHS, monthOf, shortDate, weekdayName, type ISODate } from "../_lib/tracker/dates";
import type { Session } from "../_lib/tracker/schedule";
import type { SessionLog } from "../_lib/tracker/types";
import { ValueChip } from "../_sources/ValueChip";
import { useChat } from "../_state/chat";
import { useDialogs } from "../_state/dialogs";
import { useTracker } from "../_state/tracker";
import { Icon } from "../_ui/Icon";
import type { Program } from "../types";
import { StatusGlyph, STATUS_TEXT } from "./Glyph";

export function DateHead({ date, today }: { date: ISODate; today: ISODate }) {
  const { year, month } = monthOf(date);
  return (
    <div className="sess-date">
      <span className="sess-day" aria-hidden>
        {String(dayOfMonth(date)).padStart(2, "0")}
      </span>
      <span className="sess-when">
        <span className="sess-weekday serif-i">{weekdayName(date)}</span>
        <span className="label">
          {MONTHS[month - 1]} {year}
          {date === today ? " · today" : ""}
        </span>
      </span>
    </div>
  );
}

export function RestSlab({ date, today, next, onGo }: { date: ISODate; today: ISODate; next: Session | null; onGo: (date: ISODate) => void }) {
  return (
    <article className="slab sess sess-rest" aria-label={`Rest day, ${shortDate(date)}`}>
      <DateHead date={date} today={today} />
      <p className="rest-word">Rest.</p>
      <p className="rest-text">Nothing is scheduled on this day.</p>
      {next ? (
        <button type="button" className="btn rest-next" onClick={() => onGo(next.date)}>
          <span>
            Next: {next.dayName} · {shortDate(next.date)}
          </span>
          <Icon name="right" size={14} />
        </button>
      ) : (
        <p className="rest-text quiet">No more sessions after this in the program.</p>
      )}
    </article>
  );
}

type SlabProps = {
  sessions: Session[];
  program: Program;
  today: ISODate;
  totalWeeks: number;
  logs: SessionLog[];
};

// One date's sessions (usually one). The checklist saves on every change.
export function SessionSlab({ sessions, program, today, totalWeeks, logs }: SlabProps) {
  const [pick, setPick] = useState(0);
  const session = sessions[Math.min(pick, sessions.length - 1)];
  return (
    <div className="sess-stack">
      {sessions.length > 1 && (
        <div className="seg sess-pick" role="group" aria-label="Sessions on this day">
          {sessions.map((s, i) => (
            <button key={s.key} type="button" aria-pressed={s.key === session.key} onClick={() => setPick(i)}>
              {s.dayName}
            </button>
          ))}
        </div>
      )}
      <Checklist key={session.key} session={session} program={program} today={today} totalWeeks={totalWeeks} logs={logs} />
    </div>
  );
}

function Checklist({ session, program, today, totalWeeks, logs }: { session: Session; program: Program; today: ISODate; totalWeeks: number; logs: SessionLog[] }) {
  const { commitLog } = useTracker();
  const { confirm } = useDialogs();
  const items = checklistItems(session);
  const readOnly = session.orphan;
  const logged = !!session.log;
  const doneCount = items.filter((i) => i.done).length;

  const change = (c: ChecklistChange) => {
    if (readOnly) return;
    void commitLog(session.key, applyChange(session, items, c, new Date().toISOString()));
  };

  const clear = async () => {
    if (session.log?.notes) {
      const ok = await confirm({
        title: "Clear this session?",
        body: <p>Every exercise is unchecked, and your note on this session goes with it.</p>,
        confirmLabel: "Clear session",
      });
      if (!ok) return;
    }
    change({ kind: "clear" });
  };

  const statusText = session.status === "scheduled" ? (session.date === today ? "Today" : "Scheduled") : STATUS_TEXT[session.status];

  return (
    <article className="slab sess" data-status={session.status} aria-labelledby={`sess-${session.key}`}>
      <DateHead date={session.date} today={today} />

      <div className="sess-plate">
        <h2 id={`sess-${session.key}`} className="sess-name">
          {session.dayName}
        </h2>
        <span className="sess-state">
          <StatusGlyph status={session.status} size={13} />
          {statusText}
        </span>
      </div>

      <p className="sess-meta">
        {session.block && <span>{session.block.name}</span>}
        <span>
          Week {session.weekNumber}
          {totalWeeks ? ` of ${totalWeeks}` : ""}
        </span>
        {session.deload && <span className="tag tag-hatch">Deload week</span>}
        {session.moved && (
          <span className="tag">
            <Icon name="moved" size={11} /> Moved from {shortDate(session.scheduledDate)}
          </span>
        )}
        {session.orphan && <span className="tag tag-solid">No longer in the program</span>}
      </p>

      {session.orphan && (
        <p className="caveat">
          <span className="caveat-mark">
            <Icon name="note" size={11} /> Kept
          </span>
          <span>This session’s day or week is no longer in the program. It stays here as history, as it was logged.</span>
        </p>
      )}

      {items.length === 0 ? (
        <p className="sess-empty">This day has no exercises yet. Add them on the program page.</p>
      ) : (
        <ol className="ck-list" aria-label={`${session.dayName} exercises`}>
          {items.map((item, i) => (
            <ChecklistRow
              key={item.id}
              index={i}
              item={item}
              session={session}
              program={program}
              logs={logs}
              readOnly={readOnly}
              onChange={change}
            />
          ))}
        </ol>
      )}

      {!readOnly && items.length > 0 && (
        <div className="sess-actions">
          <button type="button" className="btn btn-steel" onClick={() => change({ kind: "all" })} disabled={session.status === "completed"}>
            <Icon name="check" size={15} /> Mark all done
          </button>
          <button type="button" className="btn" onClick={clear} disabled={!logged}>
            Clear
          </button>
          <button
            type="button"
            className="btn"
            aria-pressed={session.status === "skipped"}
            onClick={() => change({ kind: "skip", skipped: session.status !== "skipped" })}
          >
            <Icon name="skip" size={15} /> {session.status === "skipped" ? "Unskip" : "Skip session"}
          </button>
          <span className="sess-count mono" aria-live="polite">
            {doneCount}/{items.length} done
          </span>
        </div>
      )}

      {!readOnly && logged && session.status !== "skipped" && (
        <label className="field sess-performed">
          <span className="field-label">Done on</span>
          <input
            type="date"
            className="input"
            value={session.log?.performedDate ?? session.scheduledDate}
            onChange={(e) => isValidISO(e.target.value) && change({ kind: "performed", date: e.target.value })}
          />
          <span className="field-hint">Trained on another day? Set it here and the calendar moves it.</span>
        </label>
      )}

      {!readOnly && logged ? (
        <NoteField key={session.key} initial={session.log?.notes ?? ""} onSave={(notes) => change({ kind: "note", notes })} />
      ) : (
        !readOnly && <p className="field-hint sess-note-hint">Check off an exercise (or skip the session) to add a note.</p>
      )}
      {session.log?.notes && readOnly && <p className="sess-note-read">{session.log.notes}</p>}
    </article>
  );
}

function ChecklistRow({
  index,
  item,
  session,
  program,
  logs,
  readOnly,
  onChange,
}: {
  index: number;
  item: ChecklistItem;
  session: Session;
  program: Program;
  logs: SessionLog[];
  readOnly: boolean;
  onChange: (c: ChecklistChange) => void;
}) {
  const { anchorTo, anchor } = useChat();
  const p = item.prescribed;
  const live = item.prescription;
  const anchored = !!live && anchor?.prescriptionId === live.id;
  // Sources belong to the live value: offer them only where the snapshot
  // still matches what the program prescribes now.
  const sources = (field: ValueField, same: boolean) =>
    live && item.slot && same ? valueSources(program, session.block, item.slot, live, field) : null;
  const prev = item.done || item.setsDone > 0 ? previousAchieved(logs, session, item) : null;
  const checkId = `ck-${session.key}-${item.id}`;

  return (
    <li className="ck" data-done={item.done || undefined} data-marker={item.marker ?? undefined} style={{ "--i": index } as React.CSSProperties}>
      <span className="ck-index mono" aria-hidden>
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="ck-box">
        <input
          id={checkId}
          type="checkbox"
          checked={item.done}
          disabled={readOnly}
          onChange={(e) => onChange({ kind: "toggle", itemId: item.id, done: e.target.checked })}
        />
        <span className="ck-stamp" aria-hidden>
          <Icon name="check" size={16} />
        </span>
      </span>
      <div className="ck-head">
        <label htmlFor={checkId} className="ck-name">
          <span className="ck-strike">{item.name}</span>
          {item.placeholder && <span className="tag">Not generated yet</span>}
          {item.marker === "added" && <span className="tag">Added since</span>}
          {item.marker === "removed" && <span className="tag tag-solid">Removed from program</span>}
        </label>
        <p className="ck-muscle">
          {capitalize(item.muscle)}
          {item.secondary.length > 0 && <span className="quiet"> · also {item.secondary.join(", ")}</span>}
        </p>
      </div>
      <div className="ck-detail">
        {!item.placeholder && (
          <div className="ck-rx">
            <ValueChip text={p.sets === 1 ? "1 set" : `${p.sets} sets`} field="sets" request={sources("sets", live?.sets === p.sets)} />
            {p.reps && <ValueChip text={`${prettyRange(p.reps)} reps`} field="reps" request={sources("reps", live?.reps === p.reps)} />}
            {p.load && <ValueChip text={p.load} field="load" request={sources("load", live?.load === p.load)} />}
            {p.rir && <ValueChip text={prettyRange(p.rir)} field="rir" request={sources("rir", live?.rir === p.rir)} />}
          </div>
        )}
        {!item.placeholder && p.sets > 0 && !readOnly && (
          <SetPips
            name={item.name}
            sets={p.sets}
            done={item.setsDone}
            onSet={(n) => onChange({ kind: "sets", itemId: item.id, setsDone: n })}
          />
        )}
        {!readOnly && (item.done || item.setsDone > 0) && (
          <Achieved
            key={`${session.key}:${item.id}`}
            initial={item.achieved}
            previous={prev}
            onSave={(achieved) => onChange({ kind: "achieved", itemId: item.id, achieved })}
          />
        )}
        {readOnly && item.achieved && (item.achieved.weight || item.achieved.reps) && (
          <p className="achieved-prev">
            Lifted: {item.achieved.weight || "—"} × {item.achieved.reps || "—"}
          </p>
        )}
      </div>
      <div className="ck-side">
        <button
          type="button"
          className="btn btn-small ck-ask"
          disabled={!live}
          aria-pressed={anchored}
          aria-label={`Ask about ${item.name}, week ${session.weekNumber}`}
          title={live ? undefined : "This exercise is no longer in the program"}
          onClick={() =>
            live &&
            anchorTo({
              prescriptionId: live.id,
              programId: program.id,
              label: `${item.slot?.exercise_name ?? item.name}, week ${session.weekNumber}`,
              thisWeekOnly: true,
            })
          }
        >
          <Icon name="ask" size={14} />
          <span>Ask</span>
        </button>
      </div>
    </li>
  );
}

function SetPips({ name, sets, done, onSet }: { name: string; sets: number; done: number; onSet: (n: number) => void }) {
  return (
    <div className="pips" role="group" aria-label={`Sets done for ${name}`}>
      {Array.from({ length: sets }, (_, i) => (
        <button
          key={i}
          type="button"
          className="pip"
          aria-pressed={i < done}
          aria-label={`Set ${i + 1} of ${sets}`}
          onClick={() => onSet(done === i + 1 ? i : i + 1)}
        />
      ))}
      <span className="pips-count mono" aria-hidden>
        {done}/{sets} sets
      </span>
    </div>
  );
}

function Achieved({
  initial,
  previous,
  onSave,
}: {
  initial?: { weight?: string; reps?: string };
  previous: { date: ISODate; weight?: string; reps?: string } | null;
  onSave: (achieved: { weight?: string; reps?: string }) => void;
}) {
  const [weight, setWeight] = useState(initial?.weight ?? "");
  const [reps, setReps] = useState(initial?.reps ?? "");
  const saved = useRef({ weight: initial?.weight ?? "", reps: initial?.reps ?? "" });

  const commit = () => {
    const w = weight.trim();
    const r = reps.trim();
    if (w === saved.current.weight && r === saved.current.reps) return;
    saved.current = { weight: w, reps: r };
    onSave({ ...(w ? { weight: w } : {}), ...(r ? { reps: r } : {}) });
  };

  return (
    <div className="achieved">
      <label className="achieved-field">
        <span className="label">Weight</span>
        <input className="input input-sm" value={weight} placeholder="60 kg" onChange={(e) => setWeight(e.target.value)} onBlur={commit} />
      </label>
      <label className="achieved-field">
        <span className="label">Reps</span>
        <input className="input input-sm" value={reps} placeholder="10, 10, 9" onChange={(e) => setReps(e.target.value)} onBlur={commit} />
      </label>
      {previous && (
        <p className="achieved-prev">
          Last time, {shortDate(previous.date)}: {previous.weight || "—"} × {previous.reps || "—"}
        </p>
      )}
    </div>
  );
}

function NoteField({ initial, onSave }: { initial: string; onSave: (notes: string) => void }) {
  const [text, setText] = useState(initial);
  const saved = useRef(initial);
  const save = useRef(onSave);
  useEffect(() => {
    save.current = onSave;
  }, [onSave]);

  // Saved shortly after typing stops, and on leaving the field.
  useEffect(() => {
    if (text === saved.current) return;
    const t = window.setTimeout(() => {
      saved.current = text;
      save.current(text);
    }, 700);
    return () => window.clearTimeout(t);
  }, [text]);

  return (
    <label className="field sess-note">
      <span className="field-label">Note</span>
      <textarea
        className="textarea"
        rows={2}
        value={text}
        placeholder="How it went, what to change next time"
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (text === saved.current) return;
          saved.current = text;
          onSave(text);
        }}
      />
    </label>
  );
}
