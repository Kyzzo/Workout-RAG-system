"use client";

import { sortedBlocks, sortedDays, weekRange } from "../_lib/format";
import { addDays, weekdayName, type ISODate } from "../_lib/tracker/dates";
import { blockOffsets, defaultOffsets } from "../_lib/tracker/schedule";
import type { Program } from "../types";

// Where each training day falls within its program week. Defaults come from
// the program's own rest spacing; where that can't place a block's days, an
// even spread is suggested for the user to confirm or adjust.
export function PlacementEditor({
  program,
  startDate,
  offsets,
  onChange,
  disabled,
}: {
  program: Program;
  startDate: ISODate;
  offsets: Record<number, number>;
  onChange: (dayId: number, offset: number) => void;
  disabled?: boolean;
}) {
  const blocks = sortedBlocks(program).filter((b) => b.day_templates.length > 0);
  return (
    <div className="place">
      {blocks.map((block) => {
        const placed = blockOffsets(block, offsets);
        const { derivable } = defaultOffsets(block);
        const days = sortedDays(block);
        const used = new Map<number, string[]>();
        for (const d of days) {
          const o = placed.get(d.id) ?? 0;
          used.set(o, [...(used.get(o) ?? []), d.name]);
        }
        return (
          <fieldset key={block.id} className="place-block" disabled={disabled}>
            <legend className="place-legend">
              <span className="display">{block.name}</span> <span className="label">{weekRange(block)}</span>
            </legend>
            {!derivable && (
              <p className="caveat">
                <span className="caveat-mark">Check</span>
                <span>
                  These days have no rest spacing to place them by, so they’re spread evenly through the week. Move any day,
                  then confirm.
                </span>
              </p>
            )}
            <div className="place-week" aria-hidden>
              {Array.from({ length: 7 }, (_, o) => (
                <span key={o} className="place-slot" data-on={used.has(o) || undefined} title={used.get(o)?.join(", ")}>
                  <span className="place-slot-day">{weekdayName(addDays(startDate, o), "short")}</span>
                  <span className="place-slot-mark" />
                </span>
              ))}
            </div>
            <div className="place-days">
              {days.map((day) => (
                <label key={day.id} className="place-day">
                  <span className="place-day-name">{day.name}</span>
                  <select
                    className="select"
                    value={placed.get(day.id) ?? 0}
                    onChange={(e) => onChange(day.id, Number(e.target.value))}
                  >
                    {Array.from({ length: 7 }, (_, o) => (
                      <option key={o} value={o}>
                        {weekdayName(addDays(startDate, o))}
                        {o === 0 ? " (week start)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}

// The overrides to store: every day of a block that couldn't be derived
// (the user confirmed it), plus any day moved from its default.
export function offsetsToStore(program: Program, edits: Record<number, number>): Record<number, number> {
  const stored: Record<number, number> = {};
  for (const block of program.mesocycles) {
    const { offsets, derivable } = defaultOffsets(block);
    for (const day of block.day_templates) {
      const chosen = edits[day.id] ?? offsets.get(day.id) ?? 0;
      if (!derivable || chosen !== offsets.get(day.id)) stored[day.id] = chosen;
    }
  }
  return stored;
}
