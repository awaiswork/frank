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

/** `2026-06-12` -> "today" / "yesterday" / "3 days ago" / "9 Jun". */
export function relativeDay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const that = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((today.getTime() - that.getTime()) / 86_400_000);
  if (diff === 0) return 'today';
  if (diff === 1) return 'yesterday';
  if (diff > 1 && diff < 7) return `${diff} days ago`;
  return that.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}
