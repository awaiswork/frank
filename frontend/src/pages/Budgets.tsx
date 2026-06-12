import { useMemo, useState } from 'react';
import { useBudgets, useCategories, useUpsertBudget } from '../api/hooks';
import type { BudgetActual, Category } from '../api/types';
import { BudgetBar } from '../components/BudgetBar';
import { FrankCallout } from '../components/bits';
import { MonthSwitcher } from '../components/MonthSwitcher';
import { Button, Card, TextInput } from '../components/ui';
import { categoryColor } from '../lib/categoryColor';
import { currentMonth } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';

export function Budgets() {
  const [month, setMonth] = useState(currentMonth());
  const categories = useCategories();
  const budgets = useBudgets(month);

  const byCategory = useMemo(() => {
    const map = new Map<string, BudgetActual>();
    for (const b of budgets.data ?? []) map.set(b.category_id, b);
    return map;
  }, [budgets.data]);

  const expenseCats = (categories.data ?? []).filter((c) => c.kind === 'expense');
  const totalSpent = (budgets.data ?? []).reduce((a, b) => a + b.spent_cents, 0);
  const totalLimit = (budgets.data ?? []).reduce((a, b) => a + b.limit_cents, 0);

  const today = new Date();
  const daysLeft =
    new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate() - today.getDate();

  return (
    <section className="animate-fade-up mx-auto flex max-w-[720px] flex-col gap-5">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em]">Budgets</h1>
            <MonthSwitcher month={month} onChange={setMonth} />
          </div>
          <p className="mt-1 max-w-[380px] text-[14px] text-muted">
            The mark shows today's pace. Past it means you're spending ahead of the month.
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-[20px] font-semibold whitespace-nowrap">
            {formatMoney(totalSpent).replace(' €', '')}{' '}
            <span className="text-[15px] text-muted">/ {formatMoney(totalLimit)}</span>
          </div>
          <div className="text-[12.5px] text-muted">spent of budgeted · {daysLeft} days left</div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {expenseCats.map((category) => (
          <BudgetRow
            key={category.id}
            category={category}
            budget={byCategory.get(category.id)}
            month={month}
            daysLeft={daysLeft}
          />
        ))}
        {expenseCats.length === 0 && <p className="text-[14px] text-muted">Loading categories…</p>}
      </div>
    </section>
  );
}

function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace('.', ',');
}

function BudgetRow({
  category,
  budget,
  month,
  daysLeft,
}: {
  category: Category;
  budget: BudgetActual | undefined;
  month: string;
  daysLeft: number;
}) {
  const upsert = useUpsertBudget(month);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(budget ? centsToInput(budget.limit_cents) : '');
  const [syncedFor, setSyncedFor] = useState(month);

  if (syncedFor !== month) {
    setSyncedFor(month);
    setValue(budget ? centsToInput(budget.limit_cents) : '');
    setEditing(false);
  }

  function save() {
    const cents = parseAmountToCents(value);
    if (cents === null) return;
    upsert.mutate(
      { categoryId: category.id, limitCents: cents },
      { onSuccess: () => setEditing(false) },
    );
  }

  const over = budget ? budget.spent_cents > budget.limit_cents : false;
  const ahead = budget ? !budget.on_track && !over : false;
  const left = budget ? budget.limit_cents - budget.spent_cents : 0;

  let note = '';
  let noteColor = 'var(--muted)';
  if (budget) {
    if (over) {
      note = `Over by ${formatMoney(budget.spent_cents - budget.limit_cents)}`;
      noteColor = 'var(--over)';
    } else if (ahead) {
      note = `${formatMoney(left)} left · ahead of pace`;
      noteColor = 'var(--wait)';
    } else {
      note = `${formatMoney(left)} left · on pace`;
      noteColor = 'var(--muted)';
    }
  }

  return (
    <Card
      className="p-[17px_19px]"
      {...(over ? { style: { boxShadow: 'var(--shadow)', borderColor: 'var(--over)' } } : {})}
    >
      <div className="mb-2.5 flex items-center justify-between gap-2.5">
        <div className="flex items-center gap-2.5 text-[15px] font-semibold whitespace-nowrap">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: categoryColor(category.name) }}
          />
          {category.name}
        </div>
        {editing || !budget ? (
          <div className="flex items-center gap-2">
            {budget && (
              <span className="num text-[14px] whitespace-nowrap text-muted">
                {formatMoney(budget.spent_cents).replace(' €', '')} /
              </span>
            )}
            <TextInput
              inputMode="decimal"
              placeholder="Limit"
              aria-label={`${category.name} monthly limit`}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="num h-9 w-24 text-[14px]"
            />
            <Button
              variant="secondary"
              className="h-9 px-3.5 text-[13px]"
              disabled={upsert.isPending}
              onClick={save}
            >
              {budget ? 'Save' : 'Set'}
            </Button>
          </div>
        ) : (
          <button
            onClick={() => setEditing(true)}
            className="num border-b border-dashed border-line-2 pb-px text-[14px] font-semibold whitespace-nowrap text-muted hover:text-ink"
          >
            {formatMoney(budget.spent_cents).replace(' €', '')} / {formatMoney(budget.limit_cents)}
          </button>
        )}
      </div>

      {budget && (
        <>
          <BudgetBar budget={budget} />
          <div className="mt-2 text-[12.5px] font-semibold" style={{ color: noteColor }}>
            {note}
          </div>
          {over && (
            <div className="mt-2.5">
              <FrankCallout tone="over">
                You've crossed the line — {daysLeft} days to go.{' '}
                <button onClick={() => setEditing(true)} className="font-semibold underline">
                  Nudge the limit?
                </button>
              </FrankCallout>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
