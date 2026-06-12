import type { BudgetActual } from '../api/types';

/**
 * Time-aware budget bar (design §components). The fill colour is *factual*, not
 * an alarm: on pace → --go, ahead of pace → --wait, over budget → --over. A 2px
 * marker sits at the share of the month elapsed.
 */
function paceColor(b: BudgetActual): string {
  if (b.spent_fraction >= 1) return 'var(--over)';
  if (!b.on_track) return 'var(--wait)';
  return 'var(--go)';
}

export function BudgetBar({ budget }: { budget: BudgetActual }) {
  const fillPct = Math.min(Math.max(budget.spent_fraction, 0), 1) * 100;
  const markerPct = Math.min(Math.max(budget.elapsed_fraction, 0), 1) * 100;

  return (
    <div className="relative h-2 w-full overflow-visible rounded-full bg-inset">
      <div
        className="animate-bar-grow h-full rounded-full"
        style={{ width: `${fillPct}%`, background: paceColor(budget) }}
      />
      <div
        className="absolute -top-0.5 h-3 w-0.5 rounded-full opacity-60"
        style={{ left: `${markerPct}%`, background: 'var(--ink-2)' }}
        aria-hidden
      />
    </div>
  );
}
