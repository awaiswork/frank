import { useState } from 'react';
import { useBudgets, useInsights } from '../api/hooks';
import { BudgetBar } from '../components/BudgetBar';
import { Capture } from '../components/Capture';
import { Money } from '../components/Money';
import { MonthSwitcher } from '../components/MonthSwitcher';
import { Card, EmptyState, SectionLabel } from '../components/ui';
import { currentMonth } from '../lib/date';

export function Home() {
  const [month, setMonth] = useState(currentMonth());
  const insights = useInsights(month);
  const budgets = useBudgets(month);

  const safe = insights.data?.safe_to_spend;
  const categories = insights.data?.spend_by_category ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-[22px] font-bold text-ink">Home</h1>
        <MonthSwitcher month={month} onChange={setMonth} />
      </div>

      <Capture />

      <Card className="text-center">
        <SectionLabel>Safe to spend</SectionLabel>
        {safe ? (
          <>
            <Money
              cents={safe.safe_to_spend_cents}
              tone={safe.safe_to_spend_cents < 0 ? 'over' : 'go'}
              className="mt-2 block text-[64px] leading-none font-semibold"
            />
            <div className="mt-5 flex justify-center gap-6 text-[13px] text-muted">
              <Stat label="Income" cents={safe.income_cents} />
              <Stat label="Spent" cents={safe.spent_cents} />
              <Stat label="Budgeted left" cents={safe.remaining_budgets_cents} />
              <Stat label="To goals" cents={safe.goal_contributions_cents} />
            </div>
          </>
        ) : (
          <p className="mt-3 text-muted">{insights.isError ? 'Could not load.' : 'Loading…'}</p>
        )}
      </Card>

      <section className="flex flex-col gap-3">
        <SectionLabel>Budgets this month</SectionLabel>
        {budgets.data && budgets.data.length > 0 ? (
          <Card className="flex flex-col gap-4">
            {budgets.data.map((b) => (
              <div key={b.category_id} className="flex flex-col gap-2">
                <div className="flex items-baseline justify-between text-[14px]">
                  <span className="flex items-center gap-2 font-medium text-ink">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: b.color ?? 'var(--muted)' }}
                    />
                    {b.category_name}
                  </span>
                  <span className="text-muted">
                    <Money cents={b.spent_cents} /> / <Money cents={b.limit_cents} tone="muted" />
                  </span>
                </div>
                <BudgetBar budget={b} />
              </div>
            ))}
          </Card>
        ) : (
          <EmptyState
            title="No budgets yet"
            hint="Set a monthly limit on the Budgets tab to track your pace."
          />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <SectionLabel>Where it went</SectionLabel>
        {categories.length > 0 ? (
          <Card className="flex flex-col gap-3">
            {categories.map((c) => (
              <div
                key={c.category_id ?? 'uncategorised'}
                className="flex items-center justify-between text-[14px]"
              >
                <span className="flex items-center gap-2 text-ink-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: c.color ?? 'var(--muted)' }}
                  />
                  {c.category_name ?? 'Uncategorised'}
                </span>
                <Money cents={c.spent_cents} />
              </div>
            ))}
          </Card>
        ) : (
          <EmptyState
            title="Nothing spent this month"
            hint="Log a transaction to see the breakdown."
          />
        )}
      </section>
    </div>
  );
}

function Stat({ label, cents }: { label: string; cents: number }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="uppercase tracking-[0.08em]">{label}</span>
      <Money cents={cents} tone="muted" className="text-[14px]" />
    </div>
  );
}
