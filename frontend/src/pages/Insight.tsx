import { useState } from 'react';
import { useInsights } from '../api/hooks';
import { FrankCallout } from '../components/bits';
import { MonthSwitcher } from '../components/MonthSwitcher';
import { Card, EmptyState } from '../components/ui';
import { categoryColor } from '../lib/categoryColor';
import { currentMonth } from '../lib/date';
import { formatMoney } from '../lib/money';

const R = 42;
const CIRC = 2 * Math.PI * R;

export function Insight() {
  const [month, setMonth] = useState(currentMonth());
  const insights = useInsights(month);

  const spend = (insights.data?.spend_by_category ?? []).filter((s) => s.spent_cents > 0);
  const mom = insights.data?.month_over_month ?? [];

  const thisTotal = spend.reduce((a, s) => a + s.spent_cents, 0);
  const prevTotal = mom.reduce((a, m) => a + m.prev_month_cents, 0);
  const delta = thisTotal - prevTotal;

  const movers = [...mom]
    .filter((m) => m.delta_cents !== 0)
    .sort((a, b) => Math.abs(b.delta_cents) - Math.abs(a.delta_cents));
  const topIncrease = movers.find((m) => m.delta_cents > 0) ?? null;
  const maxAbs = movers.length ? Math.abs(movers[0].delta_cents) : 1;

  // Donut segments — offset is the prefix sum of the slices before this one.
  const frac = (cents: number) => (thisTotal > 0 ? cents / thisTotal : 0);
  const donut = spend.map((s, i) => {
    const before = spend.slice(0, i).reduce((a, x) => a + frac(x.spent_cents), 0);
    const f = frac(s.spent_cents);
    return {
      color: categoryColor(s.category_name),
      dash: `${f * CIRC} ${CIRC - f * CIRC}`,
      offset: -before * CIRC,
    };
  });

  const headline =
    thisTotal === 0
      ? 'Nothing logged yet this month.'
      : prevTotal === 0
        ? 'Your first month with Frank.'
        : delta < 0
          ? 'A lighter month than last.'
          : delta > 0
            ? "Spending's up this month."
            : 'Holding steady with last month.';

  return (
    <section className="animate-fade-up mx-auto flex max-w-[680px] flex-col gap-3.5">
      <div className="flex items-center justify-between">
        <div className="text-[12.5px] font-bold tracking-[0.14em] text-muted uppercase">
          Your month
        </div>
        <MonthSwitcher month={month} onChange={setMonth} />
      </div>

      <h1 className="font-display text-[30px] leading-[1.15] font-semibold tracking-[-0.02em] text-balance">
        {headline}
      </h1>

      {thisTotal === 0 ? (
        <EmptyState title="No spending to analyse" hint="Log a few transactions and check back." />
      ) : (
        <>
          <p className="text-[16px] leading-relaxed text-ink-2 text-pretty">
            You've spent <Num className="text-ink">{formatMoney(thisTotal)}</Num> this month
            {prevTotal > 0 && (
              <>
                {' — '}
                <Num className={delta <= 0 ? 'text-go' : 'text-over'}>
                  {formatMoney(Math.abs(delta))}
                </Num>{' '}
                {delta <= 0 ? 'less' : 'more'} than last month
              </>
            )}
            .{' '}
            {topIncrease && (
              <>
                The line to watch is {topIncrease.category_name ?? 'uncategorised'}: up{' '}
                <Num className="text-over">{formatMoney(topIncrease.delta_cents)}</Num>.
              </>
            )}
          </p>

          {/* Where it went */}
          <Card>
            <h2 className="mb-[18px] text-[14px] font-semibold">Where it went</h2>
            <div className="flex flex-wrap items-center gap-7">
              <svg viewBox="0 0 100 100" width="132" height="132" className="shrink-0 -rotate-90">
                {donut.map((d, i) => (
                  <circle
                    key={i}
                    cx="50"
                    cy="50"
                    r={R}
                    fill="none"
                    stroke={d.color}
                    strokeWidth="13"
                    strokeDasharray={d.dash}
                    strokeDashoffset={d.offset}
                  />
                ))}
              </svg>
              <div className="flex min-w-[200px] flex-1 flex-col gap-[11px]">
                {spend.map((s) => (
                  <div key={s.category_id ?? 'unc'} className="flex items-center gap-2.5">
                    <span
                      className="h-[9px] w-[9px] shrink-0 rounded-full"
                      style={{ background: categoryColor(s.category_name) }}
                    />
                    <span className="flex-1 text-[13.5px] text-ink-2">
                      {s.category_name ?? 'Uncategorised'}
                    </span>
                    <span className="num text-[13.5px] text-muted">
                      {Math.round((s.spent_cents / thisTotal) * 100)}%
                    </span>
                    <span className="num w-[72px] text-right text-[13.5px] font-bold whitespace-nowrap">
                      {formatMoney(s.spent_cents)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* What changed */}
          {movers.length > 0 && (
            <Card>
              <h2 className="mb-[18px] text-[14px] font-semibold">What changed vs last month</h2>
              <div className="flex flex-col gap-3.5">
                {movers.slice(0, 5).map((m) => {
                  const up = m.delta_cents > 0;
                  return (
                    <div key={m.category_id ?? 'unc'} className="flex items-center gap-3.5">
                      <span className="w-24 shrink-0 text-[13.5px]">
                        {m.category_name ?? 'Uncategorised'}
                      </span>
                      <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-inset">
                        <div
                          className="absolute inset-y-0 left-0 rounded-full"
                          style={{
                            width: `${(Math.abs(m.delta_cents) / maxAbs) * 100}%`,
                            background: up ? 'var(--over)' : 'var(--go)',
                          }}
                        />
                      </div>
                      <span
                        className="num w-[72px] text-right text-[13.5px] font-bold whitespace-nowrap"
                        style={{ color: up ? 'var(--over)' : 'var(--go)' }}
                      >
                        {formatMoney(m.delta_cents, { signed: true })}
                      </span>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {topIncrease && (
            <FrankCallout>
              If you want one thing to act on: keep an eye on{' '}
              {topIncrease.category_name ?? 'that category'} next month — it's where the creep is.
            </FrankCallout>
          )}
        </>
      )}
    </section>
  );
}

function Num({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <span className={`num font-bold ${className}`}>{children}</span>;
}
