// Calendar dates as "YYYY-MM-DD" strings in the user's local calendar,
// never timestamps: a time-zone change can't move a session to another day.
// Arithmetic goes through local Y/M/D components, so DST is irrelevant.

export type ISODate = string;

const pad = (n: number) => String(n).padStart(2, "0");

export function toISO(d: Date): ISODate {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function parts(iso: ISODate): [number, number, number] {
  const [y, m, d] = iso.split("-").map(Number);
  return [y, m, d];
}

export function fromISO(iso: ISODate): Date {
  const [y, m, d] = parts(iso);
  return new Date(y, m - 1, d);
}

export function todayISO(): ISODate {
  return toISO(new Date());
}

export function addDays(iso: ISODate, n: number): ISODate {
  const [y, m, d] = parts(iso);
  return toISO(new Date(y, m - 1, d + n));
}

// Whole days from a to b (positive when b is later).
export function daysBetween(a: ISODate, b: ISODate): number {
  const [ay, am, ad] = parts(a);
  const [by, bm, bd] = parts(b);
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86_400_000);
}

export function isValidISO(iso: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
  const [y, m, d] = parts(iso);
  const date = new Date(y, m - 1, d);
  return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d;
}

// 0 = Monday ... 6 = Sunday.
export function weekday(iso: ISODate): number {
  return (fromISO(iso).getDay() + 6) % 7;
}

const WEEKDAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function weekdayName(iso: ISODate, style: "long" | "short" = "long"): string {
  return (style === "long" ? WEEKDAYS_LONG : WEEKDAYS_SHORT)[weekday(iso)];
}

export function weekdayByIndex(i: number, style: "long" | "short" = "long"): string {
  return (style === "long" ? WEEKDAYS_LONG : WEEKDAYS_SHORT)[((i % 7) + 7) % 7];
}

export function dayOfMonth(iso: ISODate): number {
  return parts(iso)[2];
}

export function monthOf(iso: ISODate): { year: number; month: number } {
  const [y, m] = parts(iso);
  return { year: y, month: m };
}

// "Thursday 23 October"
export function longDate(iso: ISODate, withYear = false): string {
  const [y, m, d] = parts(iso);
  return `${weekdayName(iso)} ${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ""}`;
}

// "Thu 23 Oct"
export function shortDate(iso: ISODate): string {
  const [, m, d] = parts(iso);
  return `${weekdayName(iso, "short")} ${d} ${MONTHS[m - 1].slice(0, 3)}`;
}

export function shiftMonth(year: number, month: number, delta: number): { year: number; month: number } {
  const index = year * 12 + (month - 1) + delta;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

// The dates shown for one month: whole rows that start on `firstWeekday`
// (0 = Monday), from the row holding the 1st to the row holding the last day.
export function monthGrid(year: number, month: number, firstWeekday: number): ISODate[] {
  const first = `${year}-${pad(month)}-01`;
  const lastDay = new Date(year, month, 0).getDate();
  const last = `${year}-${pad(month)}-${pad(lastDay)}`;
  const lead = (weekday(first) - firstWeekday + 7) % 7;
  const start = addDays(first, -lead);
  const trail = (firstWeekday + 6 - weekday(last) + 7) % 7;
  const end = addDays(last, trail);
  const count = daysBetween(start, end) + 1;
  return Array.from({ length: count }, (_, i) => addDays(start, i));
}
