import { useMemo } from 'react';
import type { NetWorth } from '../api/types';
import { formatMoney } from '../lib/money';

function monthLabel(iso: string): string {
  const [y, m] = iso.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
}

const H = 64;
const W = 300;

/**
 * Twelve points of net worth, as a line.
 *
 * Hand-rolled SVG, like the donut and bars on Insight — a polyline is not worth a
 * charting dependency.
 *
 * The part before `complete_from` is drawn **dashed and faint**, because it is not
 * comparable with the rest: an asset valued for the first time in June contributes
 * nothing to May, so the step up at June is Frankly being told about a car rather than
 * anyone acquiring one. Drawing that stretch identically would turn a data-entry event
 * into a story about getting richer.
 */
export function NetWorthTrend({ data }: { data: NetWorth }) {
  const { points, complete_from: completeFrom } = data;

  const geometry = useMemo(() => {
    const values = points.map((p) => p.total_cents);
    const min = Math.min(...values);
    const max = Math.max(...values);
    // A flat line sits in the middle rather than dividing by a zero range.
    const span = max - min || 1;
    const xy = points.map((p, i) => {
      const x = points.length === 1 ? W / 2 : (i / (points.length - 1)) * W;
      const y = H - ((p.total_cents - min) / span) * (H - 8) - 4;
      return [x, y] as const;
    });
    const firstComplete = completeFrom ? points.findIndex((p) => p.on >= completeFrom) : 0;
    const cut = firstComplete < 0 ? points.length - 1 : Math.max(firstComplete, 0);
    const path = (from: number, to: number) =>
      xy
        .slice(from, to + 1)
        .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
        .join(' ');
    return {
      incomplete: cut > 0 ? path(0, cut) : '',
      complete: path(cut, points.length - 1),
      last: xy[xy.length - 1],
      cut,
    };
  }, [points, completeFrom]);

  if (points.length < 2) return null;

  const last = points[points.length - 1];
  // Measured across the *comparable* stretch only. Running it from the first point
  // would announce "up 10 500,00 €" on a line whose own caption says the early part is
  // missing things — the summary asserting exactly what the dashing warns against.
  const from = points[geometry.cut];
  const change = last.total_cents - from.total_cents;
  const comparable = points.length - geometry.cut;

  return (
    <div className="flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-[64px] w-full"
        role="img"
        aria-label={`Net worth over the last ${points.length} months, now ${formatMoney(last.total_cents)}`}
      >
        {geometry.incomplete && (
          <polyline
            points={geometry.incomplete}
            fill="none"
            stroke="var(--faint)"
            strokeWidth="1.5"
            strokeDasharray="3 4"
            vectorEffect="non-scaling-stroke"
          />
        )}
        <polyline
          points={geometry.complete}
          fill="none"
          stroke="var(--ink-2)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        <circle cx={geometry.last[0]} cy={geometry.last[1]} r="2.5" fill="var(--ink)" />
      </svg>

      <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-[12.5px] text-muted">
        <span>
          {comparable < 2
            ? 'Not enough history to compare yet'
            : change === 0
              ? `Flat since ${monthLabel(from.on)}`
              : `${change > 0 ? 'Up' : 'Down'} ${formatMoney(Math.abs(change))} since ${monthLabel(from.on)}`}
        </span>
        {/* Says plainly why the dashed part is dashed, rather than leaving a reader to
            infer that they got richer the month they added their car. */}
        {geometry.incomplete && (
          <span className="text-faint">Dashed: before everything here was on file</span>
        )}
      </div>
    </div>
  );
}
