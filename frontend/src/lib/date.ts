/** Date helpers. Months are the `YYYY-MM` strings the API expects. */

export function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/** `2026-06` -> `June 2026`. */
export function monthLabel(month: string): string {
  const [year, mon] = month.split('-').map(Number);
  return `${MONTH_NAMES[mon - 1]} ${year}`;
}

/** Shift a `YYYY-MM` month by ±n months. */
export function shiftMonth(month: string, delta: number): string {
  const [year, mon] = month.split('-').map(Number);
  const d = new Date(Date.UTC(year, mon - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
}
