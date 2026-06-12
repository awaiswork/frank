/**
 * Money helpers. The backend stores integer cents; the client never does float
 * math. Display format follows the design system: thin-space (U+202F) grouping,
 * comma decimal, trailing "€" — e.g. `1 247,30 €`.
 *
 * Special characters are built from code points so they survive editors/diffs:
 * U+202F narrow no-break space (grouping), U+00A0 no-break space (before €),
 * U+2212 minus sign (not a hyphen).
 */

const THIN_SPACE = String.fromCharCode(0x202f);
const NBSP = String.fromCharCode(0x00a0);
const MINUS = String.fromCharCode(0x2212);

export function formatMoney(cents: number, { signed = false }: { signed?: boolean } = {}): string {
  const negative = cents < 0;
  const abs = Math.abs(Math.round(cents));
  const whole = Math.floor(abs / 100).toString();
  const frac = (abs % 100).toString().padStart(2, '0');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, THIN_SPACE);
  const sign = negative ? MINUS : signed ? '+' : '';
  return `${sign}${grouped},${frac}${NBSP}€`;
}

/** Split into euros (thin-space grouped) and cents for the big hero figure. */
export function moneyParts(cents: number): { negative: boolean; euros: string; cents: string } {
  const negative = cents < 0;
  const abs = Math.abs(Math.round(cents));
  const euros = Math.floor(abs / 100)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, THIN_SPACE);
  return { negative, euros, cents: (abs % 100).toString().padStart(2, '0') };
}

export const MINUS_SIGN = MINUS;

/**
 * Parse a user-typed amount ("12,50", "12.50", "1 200") into integer cents.
 * Returns null for anything that isn't a positive amount. (JS `\s` already
 * matches the thin/no-break spaces, so stripping whitespace is enough.)
 */
export function parseAmountToCents(input: string): number | null {
  const cleaned = input.trim().replace(/[\s€]/g, '').replace(',', '.');
  if (cleaned === '' || !/^\d*\.?\d*$/.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value <= 0) return null;
  return Math.round(value * 100);
}
