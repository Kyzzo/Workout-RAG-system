"use client";

import { useState } from "react";
import { valueSources, type ValueField } from "../_lib/evidence";
import {
  blockHasPlaceholder,
  blockVaries,
  blockWeekNumbers,
  capitalize,
  direction,
  isDeloadWeek,
  isPlaceholder,
  plural,
  prescriptionFor,
  prettyRange,
  rowsToShow,
  sortedDays,
  sortedSlots,
  weekRange,
} from "../_lib/format";
import { Caveat } from "../_sources/RuleSources";
import { ValueChip } from "../_sources/ValueChip";
import { useApp } from "../_state/app";
import { useChat } from "../_state/chat";
import { Icon } from "../_ui/Icon";
import { Menu, type MenuItem } from "../_ui/Menu";
import type { DayTemplate, ExerciseSlot, Mesocycle, Program, WeeklyPrescription } from "../types";
import { AddDayForm, AddExerciseForm } from "./Forms";
import { MuscleAnalysis } from "./MuscleAnalysis";
import { useProgramOps } from "./useProgramOps";

type View = "every" | "all" | number;

export function BlockSection({ block, program, index }: { block: Mesocycle; program: Program; index: number }) {
  const { generateBlock, locked } = useApp();
  const ops = useProgramOps(program);
  const varies = blockVaries(block, program.goal);
  const weeks = blockWeekNumbers(block);
  const [picked, setPicked] = useState<View | null>(null);
  // A week that no longer exists falls back to the block's default view.
  const fallback: View = varies ? weeks[0] : "every";
  const view: View =
    picked === null || (typeof picked === "number" && !weeks.includes(picked)) || (picked === "every" && varies) || (picked === "all" && !varies)
      ? fallback
      : picked;
  const hasExercises = block.day_templates.some((d) => d.exercise_slots.length > 0);
  const placeholders = blockHasPlaceholder(block);
  const days = sortedDays(block);

  return (
    <section className="block" aria-labelledby={`block-${block.id}`} style={{ "--i": index } as React.CSSProperties}>
      <header className="block-head">
        <div className="block-id">
          <span className="block-no mono" aria-hidden>
            B{String(index + 1).padStart(2, "0")}
          </span>
          <h2 id={`block-${block.id}`} className="block-name display">
            {block.name}
          </h2>
          <span className="block-weeks label">{weekRange(block)}</span>
          {!varies && <span className="tag">Same every week</span>}
        </div>
        <div className="block-tools">
          {hasExercises && (
            <button type="button" className="btn btn-steel btn-small" disabled={locked} onClick={() => void generateBlock(block)}>
              <Icon name="bolt" size={14} />
              {placeholders ? "Generate block" : "Regenerate block"}
            </button>
          )}
          <Menu
            label={`${block.name} options`}
            disabled={locked}
            items={[{ label: "Rename block", icon: "edit", onSelect: () => void ops.rename("block", block) }]}
          />
        </div>
      </header>

      {weeks.length > 1 && hasExercises && (
        <div className="block-view">
          <label className="field block-view-field">
            <span className="field-label">Showing</span>
            <select
              className="select"
              value={String(view)}
              onChange={(e) => {
                const v = e.target.value;
                setPicked(v === "every" || v === "all" ? v : Number(v));
              }}
            >
              {!varies && <option value="every">Every week</option>}
              {weeks.map((w) => (
                <option key={w} value={w}>
                  Week {w}
                  {isDeloadWeek(program, block, w) ? " (deload)" : ""}
                </option>
              ))}
              {varies && <option value="all">All weeks</option>}
            </select>
          </label>
          {!varies && typeof view === "number" && (
            <p className="scope-note" role="status">
              <Icon name="flag" size={13} /> Changes made here apply to week {view} only.
            </p>
          )}
        </div>
      )}

      <MuscleAnalysis block={block} program={program} />

      <div className="days">
        {days.map((day, i) => (
          <DayCard key={day.id} day={day} block={block} program={program} view={view} index={i} />
        ))}
      </div>
      <AddDayForm block={block} />
    </section>
  );
}

function DayCard({ day, block, program, view, index }: { day: DayTemplate; block: Mesocycle; program: Program; view: View; index: number }) {
  const { locked, busy } = useApp();
  const ops = useProgramOps(program);
  const slots = sortedSlots(day.exercise_slots);
  const working = busy?.scope === `day:${day.id}` ? busy.working : null;
  return (
    <article className="day" aria-labelledby={`day-${day.id}`} data-working={working ? "" : undefined}>
      <header className="day-head">
        <span className="day-no mono" aria-hidden>
          D{index + 1}
        </span>
        <h3 id={`day-${day.id}`} className="day-name display">
          {day.name}
        </h3>
        <span className="day-meta label">
          {plural(slots.length, "exercise")}
          {day.rest_days_before !== null && ` · ${plural(day.rest_days_before, "rest day")} before`}
        </span>
        {working && <span className="tag scanline">{working}</span>}
        <Menu
          label={`${day.name} options`}
          disabled={locked}
          items={[
            { label: "Rename day", icon: "edit", onSelect: () => void ops.rename("day", day) },
            "sep",
            { label: "Delete day", icon: "trash", danger: true, onSelect: () => void ops.deleteDay(day) },
          ]}
        />
      </header>
      {slots.length === 0 && <p className="day-empty">No exercises on this day yet.</p>}
      <ol className="exercises">
        {slots.map((slot, i) => (
          <ExerciseCard key={slot.id} slot={slot} index={i} block={block} program={program} view={view} />
        ))}
      </ol>
      <AddExerciseForm day={day} />
    </article>
  );
}

type RowSpec = { kind: "every" | "week"; p: WeeklyPrescription; prev: WeeklyPrescription | null };

function rowsFor(slot: ExerciseSlot, goal: string, view: View): RowSpec[] {
  if (typeof view === "number") {
    const p = prescriptionFor(slot, view);
    return p ? [{ kind: "week", p, prev: prescriptionFor(slot, view - 1) }] : [];
  }
  return rowsToShow(slot, goal).map((r) => ({ ...r, prev: null }));
}

function ExerciseCard({ slot, index, block, program, view }: { slot: ExerciseSlot; index: number; block: Mesocycle; program: Program; view: View }) {
  const { locked, busy } = useApp();
  const ops = useProgramOps(program);
  const strength = program.goal === "strength";
  const rows = rowsFor(slot, program.goal, view);
  const showLoad = strength || slot.weekly_prescriptions.some((p) => !!p.load);
  const working = busy?.scope === `slot:${slot.id}` ? busy.working : null;
  const single = rows.length === 1 ? rows[0] : null;

  const items: MenuItem[] = [
    { label: "Generate reps & effort", icon: "bolt", onSelect: () => void ops.generateExercise(slot) },
    ...(single && single.kind === "week"
      ? ([
          { label: `Regenerate sets (week ${single.p.week_number})`, icon: "spark", onSelect: () => void ops.regenerateSets(slot, single.p) },
          ...(strength
            ? [{ label: `Regenerate load (week ${single.p.week_number})`, icon: "spark", onSelect: () => void ops.regenerateLoad(slot, single.p) }]
            : []),
        ] as MenuItem[])
      : []),
    { label: "Swap exercise", icon: "swap", onSelect: () => void ops.swap(slot) },
    "sep",
    { label: "Delete exercise", icon: "trash", danger: true, onSelect: () => void ops.deleteExercise(slot) },
  ];

  return (
    <li className="ex" data-working={working ? "" : undefined} style={{ "--i": index } as React.CSSProperties}>
      <div className="ex-head">
        <span className="ex-no mono" aria-hidden>
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="ex-id">
          <h4 className="ex-name">{slot.exercise_name}</h4>
          <p className="ex-muscle">
            {capitalize(slot.muscle_group)}
            {slot.secondary_muscle_groups.length > 0 && <span className="quiet"> · also {slot.secondary_muscle_groups.join(", ")}</span>}
          </p>
        </div>
        {working && (
          <span className="tag scanline ex-working" role="status">
            {working}
          </span>
        )}
        <Menu label={`${slot.exercise_name} options`} disabled={locked} items={items} />
      </div>
      {single ? (
        <SingleRow row={single} slot={slot} block={block} program={program} showLoad={showLoad} />
      ) : (
        <RowTable rows={rows} slot={slot} block={block} program={program} showLoad={showLoad} />
      )}
    </li>
  );
}

function useAsk(program: Program, slot: ExerciseSlot) {
  const { anchorTo, anchor } = useChat();
  return {
    anchoredId: anchor?.prescriptionId ?? null,
    ask: (row: RowSpec) =>
      anchorTo({
        prescriptionId: row.p.id,
        programId: program.id,
        label: row.kind === "every" ? slot.exercise_name : `${slot.exercise_name}, week ${row.p.week_number}`,
        thisWeekOnly: row.kind !== "every",
      }),
  };
}

function chips(row: RowSpec, slot: ExerciseSlot, block: Mesocycle, program: Program, showLoad: boolean, withDirection: boolean) {
  const p = row.p;
  const prev = withDirection ? row.prev : null;
  const dir = (a: string | number | undefined, b: string | number) => (prev && a !== undefined ? direction(a, b) : null);
  const req = (field: ValueField) => valueSources(program, block, slot, p, field);
  return {
    sets: <ValueChip text={p.sets === 0 ? "—" : p.sets === 1 ? "1 set" : `${p.sets} sets`} field="sets" request={req("sets")} direction={dir(prev?.sets, p.sets)} previous={prev ? `${prev.sets} sets` : undefined} />,
    reps: <ValueChip text={p.reps ? prettyRange(p.reps) : "—"} field="reps" request={req("reps")} direction={dir(prev?.reps, p.reps)} previous={prev?.reps} />,
    load: showLoad ? <ValueChip text={p.load || "—"} field="load" request={req("load")} direction={dir(prev?.load, p.load)} previous={prev?.load} /> : null,
    rir: <ValueChip text={p.rir ? prettyRange(p.rir) : "—"} field="rir" request={req("rir")} direction={dir(prev?.rir, p.rir)} previous={prev?.rir} />,
  };
}

function SingleRow({ row, slot, block, program, showLoad }: { row: RowSpec; slot: ExerciseSlot; block: Mesocycle; program: Program; showLoad: boolean }) {
  const { ask, anchoredId } = useAsk(program, slot);
  const placeholder = isPlaceholder(row.p);
  const c = chips(row, slot, block, program, showLoad, row.kind === "week");
  const anchored = anchoredId === row.p.id;
  return (
    <div className="rx" data-anchored={anchored || undefined}>
      {placeholder ? (
        <p className="rx-pending">
          <span className="tag tag-hatch">Not generated yet</span>
        </p>
      ) : (
        <dl className="rx-cells" data-load={showLoad || undefined}>
          <div>
            <dt className="label">Sets</dt>
            <dd>{c.sets}</dd>
          </div>
          <div>
            <dt className="label">Reps</dt>
            <dd>{c.reps}</dd>
          </div>
          {showLoad && (
            <div>
              <dt className="label">Load</dt>
              <dd>{c.load}</dd>
            </div>
          )}
          <div>
            <dt className="label">Effort</dt>
            <dd>{c.rir}</dd>
          </div>
        </dl>
      )}
      <div className="rx-foot">
        <span className="rx-scope label">
          {row.kind === "every" ? "Every week" : `Week ${row.p.week_number}`}
          {isDeloadWeek(program, block, row.p.week_number) && row.kind === "week" ? " · deload" : ""}
        </span>
        <button
          type="button"
          className="btn btn-small rx-ask"
          aria-pressed={anchored}
          aria-label={`Ask about ${slot.exercise_name}${row.kind === "week" ? `, week ${row.p.week_number}` : ""}`}
          onClick={() => ask(row)}
        >
          <Icon name="ask" size={14} />
          <span>Ask</span>
        </button>
      </div>
      {!placeholder && row.p.load_fit_note && <Caveat text={row.p.load_fit_note} mark="Fit" />}
    </div>
  );
}

function RowTable({ rows, slot, block, program, showLoad }: { rows: RowSpec[]; slot: ExerciseSlot; block: Mesocycle; program: Program; showLoad: boolean }) {
  const { locked, busy } = useApp();
  const ops = useProgramOps(program);
  const { ask, anchoredId } = useAsk(program, slot);
  const strength = program.goal === "strength";
  return (
    <div className="rx-table-wrap">
      <table className="rx-table" data-load={showLoad || undefined}>
        <thead>
          <tr>
            <th scope="col" className="label">
              Wk
            </th>
            <th scope="col" className="label">
              Sets
            </th>
            <th scope="col" className="label">
              Reps
            </th>
            {showLoad && (
              <th scope="col" className="label">
                Load
              </th>
            )}
            <th scope="col" className="label">
              Effort
            </th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const p = row.p;
            const c = chips(row, slot, block, program, showLoad, false);
            const placeholder = isPlaceholder(p);
            const working = busy?.scope === `row:${p.id}` ? busy.working : null;
            const anchored = anchoredId === p.id;
            return (
              <tr key={p.id} data-anchored={anchored || undefined} data-working={working ? "" : undefined}>
                <th scope="row" className="rx-wk mono">
                  {row.kind === "every" ? "All" : String(p.week_number).padStart(2, "0")}
                  {isDeloadWeek(program, block, p.week_number) && row.kind === "week" && <span className="rx-dl">DL</span>}
                </th>
                {placeholder ? (
                  <td colSpan={showLoad ? 4 : 3} className="rx-pending-cell">
                    <span className="tag tag-hatch">Not generated yet</span>
                  </td>
                ) : (
                  <>
                    <td>{c.sets}</td>
                    <td>{c.reps}</td>
                    {showLoad && <td>{c.load}</td>}
                    <td>{c.rir}</td>
                  </>
                )}
                <td className="rx-actions">
                  {working && <span className="sr-only" role="status">{working}</span>}
                  <button
                    type="button"
                    className="btn btn-quiet btn-icon btn-small"
                    aria-pressed={anchored}
                    aria-label={`Ask about ${slot.exercise_name}${row.kind === "week" ? `, week ${p.week_number}` : ""}`}
                    title="Ask"
                    onClick={() => ask(row)}
                  >
                    <Icon name="ask" size={15} />
                  </button>
                  {row.kind === "week" && (
                    <Menu
                      label={`Week ${p.week_number} options`}
                      disabled={locked}
                      items={[
                        { label: `Regenerate sets (week ${p.week_number})`, icon: "spark", onSelect: () => void ops.regenerateSets(slot, p) },
                        ...(strength
                          ? [{ label: `Regenerate load (week ${p.week_number})`, icon: "spark" as const, onSelect: () => void ops.regenerateLoad(slot, p) }]
                          : []),
                      ]}
                    />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows
        .filter((r) => !isPlaceholder(r.p) && r.p.load_fit_note)
        .map((r) => (
          <Caveat key={r.p.id} text={`Week ${r.p.week_number}: ${r.p.load_fit_note}`} mark="Fit" />
        ))}
    </div>
  );
}
