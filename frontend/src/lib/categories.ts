import type { Category, Kind, Transaction } from '../api/types';

/**
 * Rank the user's categories by how often they actually use them, so the chips a
 * person taps most sit first in the quick-add sheet.
 *
 * Ties keep the server's order — chips must not reshuffle between renders, or
 * muscle memory stops working. Categories they've never used still appear, just
 * after the ones they have.
 */
export function rankCategories(
  categories: Category[],
  transactions: Transaction[],
  kind: Kind,
): Category[] {
  const uses = new Map<string, number>();
  for (const t of transactions) {
    if (t.kind !== kind || !t.category_id) continue;
    uses.set(t.category_id, (uses.get(t.category_id) ?? 0) + 1);
  }
  return categories
    .filter((c) => c.kind === kind)
    .map((c, i) => ({ c, n: uses.get(c.id) ?? 0, i }))
    .sort((a, b) => b.n - a.n || a.i - b.i)
    .map(({ c }) => c);
}
