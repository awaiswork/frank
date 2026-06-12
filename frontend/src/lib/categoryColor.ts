/**
 * Map a category name to its CSS colour variable so colours stay correct in both
 * light and dark themes (the backend stores a single hex; the design swaps per
 * theme). Falls back to a passed colour for custom categories.
 */
const MAP: Record<string, string> = {
  groceries: 'var(--cat-grocery)',
  'eating out': 'var(--cat-dining)',
  dining: 'var(--cat-dining)',
  transport: 'var(--cat-transport)',
  fun: 'var(--cat-fun)',
  bills: 'var(--cat-bills)',
  health: 'var(--cat-health)',
  income: 'var(--go)',
  savings: 'var(--cat-savings)',
};

export function categoryColor(name: string | null | undefined, fallback = 'var(--muted)'): string {
  if (!name) return fallback;
  return MAP[name.trim().toLowerCase()] ?? fallback;
}

/** Soft tint used behind category-initial avatars and chips. */
export function categoryTint(name: string | null | undefined): string {
  return `color-mix(in oklab, ${categoryColor(name)} 16%, transparent)`;
}
