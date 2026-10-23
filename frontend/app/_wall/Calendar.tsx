"use client";

import { useEffect, useRef } from "react";
import {
  addDays,
  dayOfMonth,
  longDate,
  MONTHS,
  monthGrid,
  monthOf,
  weekdayByIndex,
  type ISODate,
} from "../_lib/tracker/dates";
import { weekOfDate, type Session } from "../_lib/tracker/schedule";
import { Icon } from "../_ui/Icon";
import { StatusGlyph, STATUS_TEXT } from "./Glyph";

type Props = {
  year: number;
  month: number;
  firstWeekday: number;
  byDate: Map<ISODate, Session[]>;
  today: ISODate;
  selected: ISODate;
  rangeStart: ISODate;
  rangeEnd: ISODate;
  startDate: ISODate;
  totalWeeks: number;
  onSelect: (date: ISODate, follow: boolean) => void;
  onMonth: (delta: number) => void;
  onToday: () => void;
};

// The month as a cast wall: one row per program week, each day a formwork
// panel. Today is the one under the lamp.
export function Calendar(props: Props) {
  const { year, month, firstWeekday, byDate, today, selected, rangeStart, rangeEnd, startDate, totalWeeks } = props;
  const dates = monthGrid(year, month, firstWeekday);
  const rows: ISODate[][] = [];
  for (let i = 0; i < dates.length; i += 7) rows.push(dates.slice(i, i + 7));
  const grid = useRef<HTMLDivElement>(null);
  const keyed = useRef(false);

  const selectable = (date: ISODate) => (date >= rangeStart && date <= rangeEnd) || byDate.has(date);

  // After arrow-key moves, keep focus on the newly selected day.
  useEffect(() => {
    if (!keyed.current) return;
    keyed.current = false;
    grid.current?.querySelector<HTMLButtonElement>(`[data-date="${selected}"]`)?.focus();
  }, [selected, year, month]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (!step) return;
    e.preventDefault();
    let next = addDays(selected, step);
    // Skip inert days in the direction of travel (bounded).
    for (let i = 0; i < 62 && !selectable(next); i++) next = addDays(next, step > 0 ? 1 : -1);
    if (!selectable(next)) return;
    keyed.current = true;
    props.onSelect(next, true);
  };

  const label = `${MONTHS[month - 1]} ${year}`;
  const thisMonth = monthOf(today);
  const onTodayMonth = thisMonth.year === year && thisMonth.month === month;

  return (
    <div className="cal">
      <div className="cal-bar">
        <button type="button" className="btn btn-quiet btn-icon" aria-label="Previous month" onClick={() => props.onMonth(-1)}>
          <Icon name="left" />
        </button>
        <h2 className="cal-month" aria-live="polite">
          <span className="display">{MONTHS[month - 1]}</span> <span className="cal-year mono">{year}</span>
        </h2>
        <button type="button" className="btn btn-quiet btn-icon" aria-label="Next month" onClick={() => props.onMonth(1)}>
          <Icon name="right" />
        </button>
        <button type="button" className="btn btn-small cal-today" onClick={props.onToday} aria-pressed={onTodayMonth && selected === today}>
          <Icon name="today" size={14} />
          Today
        </button>
      </div>

      <div ref={grid} role="grid" aria-label={label} className="cal-grid" onKeyDown={onKeyDown} key={`${year}-${month}`}>
        <div role="row" className="cal-row cal-head">
          <span role="columnheader" className="cal-wk" aria-label="Program week">
            Wk
          </span>
          {Array.from({ length: 7 }, (_, i) => (
            <span key={i} role="columnheader" className="cal-dow" aria-label={weekdayByIndex(firstWeekday + i)}>
              {weekdayByIndex(firstWeekday + i, "short")}
            </span>
          ))}
        </div>
        {rows.map((row, r) => {
          const week = weekOfDate(startDate, row[0]);
          const showWeek = week >= 1 && week <= totalWeeks;
          return (
            <div role="row" className="cal-row" key={row[0]} style={{ "--r": r } as React.CSSProperties}>
              <span role="rowheader" className="cal-wk">
                {showWeek ? (
                  <>
                    <span aria-hidden>{String(week).padStart(2, "0")}</span>
                    <span className="sr-only">Week {week}</span>
                  </>
                ) : (
                  <span className="sr-only">Outside the program</span>
                )}
              </span>
              {row.map((date, c) => {
                const sessions = byDate.get(date) ?? [];
                const out = monthOf(date).month !== month;
                const isToday = date === today;
                const isSelected = date === selected;
                if (!selectable(date)) {
                  return (
                    <div key={date} role="gridcell" aria-disabled="true" className="cal-cell" data-inert data-out={out || undefined} data-today={isToday || undefined} style={{ "--c": c } as React.CSSProperties}>
                      <span className="cal-num" aria-hidden>
                        {dayOfMonth(date)}
                      </span>
                      <span className="sr-only">{longDate(date)}, outside the program</span>
                    </div>
                  );
                }
                const description = sessions.length
                  ? sessions
                      .map(
                        (s) =>
                          `${s.dayName}, week ${s.weekNumber}${totalWeeks ? ` of ${totalWeeks}` : ""}, ${STATUS_TEXT[s.status].toLowerCase()}${s.deload ? ", deload week" : ""}${s.moved ? ", moved here" : ""}${s.orphan ? ", no longer in the program" : ""}`,
                      )
                      .join("; ")
                  : "rest day";
                return (
                  <div key={date} role="gridcell" aria-selected={isSelected} className="cal-cell-wrap">
                    <button
                      type="button"
                      className="cal-cell"
                      data-date={date}
                      data-out={out || undefined}
                      data-today={isToday || undefined}
                      data-selected={isSelected || undefined}
                      data-has={sessions.length ? "" : undefined}
                      tabIndex={isSelected ? 0 : -1}
                      aria-current={isToday ? "date" : undefined}
                      aria-label={`${longDate(date)}${isToday ? ", today" : ""}. ${description}.`}
                      style={{ "--c": c } as React.CSSProperties}
                      onClick={() => props.onSelect(date, false)}
                    >
                      <span className="cal-num" aria-hidden>
                        {dayOfMonth(date)}
                      </span>
                      {isToday && (
                        <span className="cal-today-tag" aria-hidden>
                          Today
                        </span>
                      )}
                      <span className="cal-marks" aria-hidden>
                        {sessions.map((s) => (
                          <span key={s.key} className="cal-mark" data-status={s.status}>
                            <StatusGlyph status={s.status} size={11} />
                            <span className="cal-mark-name">{s.dayName}</span>
                            {s.deload && <span className="cal-flag">DL</span>}
                            {s.moved && <Icon name="moved" size={11} />}
                          </span>
                        ))}
                      </span>
                    </button>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      <ul className="cal-legend" aria-label="Legend">
        {(["scheduled", "completed", "partial", "skipped", "missed"] as const).map((s) => (
          <li key={s}>
            <StatusGlyph status={s} size={11} />
            {STATUS_TEXT[s]}
          </li>
        ))}
        <li>
          <span className="cal-flag">DL</span> Deload
        </li>
        <li>
          <Icon name="moved" size={11} /> Moved
        </li>
      </ul>
    </div>
  );
}
