import { useMemo, useState } from 'react';
import { useBudgets, useCategories, useUpsertBudget } from '../api/hooks';
import type { BudgetActual, Category } from '../api/types';
import { BudgetBar } from '../components/BudgetBar';
import { Money } from '../components/Money';
import { MonthSwitcher } from '../components/MonthSwitcher';
import { Button, Card, TextInput } from '../components/ui';
import { currentMonth } from '../lib/date';
import { parseAmountToCents } from '../lib/money';

export function Budgets() {
  const [month, setMonth] = useState(currentMonth());
  const categories = useCategories();
  const budgets = useBudgets(month);

  const budgetByCategory = useMemo(() => {
    const map = new Map<string, BudgetActual>();
    for (const b of budgets.data ?? []) map.set(b.category_id, b);
    return map;
  }, [budgets.data]);

  const expenseCategories = (categories.data ?? []).filter((c) => c.kind === 'expense');

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-[22px] font-bold text-ink">Budgets</h1>
        <MonthSwitcher month={month} onChange={setMonth} />
      </div>

      <Card className="flex flex-col gap-5">
        {expenseCategories.map((category) => (
          <BudgetRow
            key={category.id}
            category={category}
            budget={budgetByCategory.get(category.id)}
            month={month}
          />
        ))}
        {expenseCategories.length === 0 && (
          <p className="text-[14px] text-muted">Loading categories…</p>
        )}
      </Card>
    </div>
  );
}

function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace('.', ',');
}

function BudgetRow({
  category,
  budget,
  month,
}: {
  category: Category;
  budget: BudgetActual | undefined;
  month: string;
}) {
  const upsert = useUpsertBudget(month);
  const [value, setValue] = useState(budget ? centsToInput(budget.limit_cents) : '');
  const [error, setError] = useState(false);

  // Keep the field in sync when the month (and thus the budget) changes.
  const [syncedFor, setSyncedFor] = useState(month);
  if (syncedFor !== month) {
    setSyncedFor(month);
    setValue(budget ? centsToInput(budget.limit_cents) : '');
  }

  function save() {
    const cents = parseAmountToCents(value);
    if (cents === null) {
      setError(true);
      return;
    }
    setError(false);
    upsert.mutate({ categoryId: category.id, limitCents: cents });
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[14.5px] font-medium text-ink">
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{ background: category.color ?? 'var(--muted)' }}
          />
          {category.name}
        </span>
        <div className="flex items-center gap-2">
          <TextInput
            inputMode="decimal"
            placeholder="Limit"
            aria-label={`${category.name} monthly limit`}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={`h-9 w-28 text-[14px] ${error ? 'border-over' : ''}`}
          />
          <Button
            variant="secondary"
            className="h-9 px-4 text-[13px]"
            disabled={upsert.isPending}
            onClick={save}
          >
            {budget ? 'Update' : 'Set'}
          </Button>
        </div>
      </div>

      {budget && (
        <>
          <BudgetBar budget={budget} />
          <p className="text-[12px] text-muted">
            <Money cents={budget.spent_cents} /> of{' '}
            <Money cents={budget.limit_cents} tone="muted" /> spent ·{' '}
            {Math.round(budget.spent_fraction * 100)}% at{' '}
            {Math.round(budget.elapsed_fraction * 100)}% of the month
          </p>
        </>
      )}
    </div>
  );
}
