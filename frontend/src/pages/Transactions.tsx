import { useMemo, useState, type FormEvent } from 'react';
import {
  useCategories,
  useCreateTransaction,
  useDeleteTransaction,
  useTransactions,
} from '../api/hooks';
import type { Category, Kind } from '../api/types';
import { Money } from '../components/Money';
import { MonthSwitcher } from '../components/MonthSwitcher';
import { Button, Card, EmptyState, Field, SectionLabel, TextInput } from '../components/ui';
import { currentMonth, todayISO } from '../lib/date';
import { parseAmountToCents } from '../lib/money';

export function Transactions() {
  const [month, setMonth] = useState(currentMonth());
  const [q, setQ] = useState('');
  const categories = useCategories();
  const transactions = useTransactions({ month, q: q.trim() || undefined });

  const categoryById = useMemo(() => {
    const map = new Map<string, Category>();
    for (const c of categories.data ?? []) map.set(c.id, c);
    return map;
  }, [categories.data]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-[22px] font-bold text-ink">Transactions</h1>
        <MonthSwitcher month={month} onChange={setMonth} />
      </div>

      <AddTransaction categories={categories.data ?? []} />

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <SectionLabel>This month</SectionLabel>
          <TextInput
            className="h-9 max-w-[200px] text-[14px]"
            placeholder="Search…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        {transactions.data && transactions.data.length > 0 ? (
          <Card className="flex flex-col divide-y divide-line p-0">
            {transactions.data.map((t) => {
              const cat = t.category_id ? categoryById.get(t.category_id) : undefined;
              const income = t.kind === 'income';
              return (
                <div key={t.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-[14.5px] font-medium text-ink">{t.description}</p>
                    <p className="text-[12px] text-muted">
                      {t.occurred_on}
                      {cat && (
                        <>
                          {' · '}
                          <span style={{ color: cat.color ?? undefined }}>{cat.name}</span>
                        </>
                      )}
                      {t.merchant ? ` · ${t.merchant}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Money
                      cents={income ? t.amount_cents : -t.amount_cents}
                      signed={income}
                      tone={income ? 'go' : 'default'}
                      className="text-[14.5px]"
                    />
                    <DeleteButton id={t.id} />
                  </div>
                </div>
              );
            })}
          </Card>
        ) : (
          <EmptyState
            title={q ? 'No matches' : 'No transactions yet'}
            hint={q ? 'Try a different search.' : 'Add your first one above.'}
          />
        )}
      </section>
    </div>
  );
}

function DeleteButton({ id }: { id: string }) {
  const del = useDeleteTransaction();
  return (
    <button
      type="button"
      aria-label="Delete transaction"
      disabled={del.isPending}
      onClick={() => del.mutate(id)}
      className="text-[18px] leading-none text-faint hover:text-over disabled:opacity-40"
    >
      ×
    </button>
  );
}

function AddTransaction({ categories }: { categories: Category[] }) {
  const create = useCreateTransaction();
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [kind, setKind] = useState<Kind>('expense');
  const [occurredOn, setOccurredOn] = useState(todayISO());
  const [error, setError] = useState<string | null>(null);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const cents = parseAmountToCents(amount);
    if (cents === null) {
      setError('Enter an amount like 12,50');
      return;
    }
    if (!description.trim()) {
      setError('Add a short description');
      return;
    }
    setError(null);
    create.mutate(
      {
        amount_cents: cents,
        description: description.trim(),
        kind,
        occurred_on: occurredOn,
        category_id: categoryId || null,
      },
      {
        onSuccess: () => {
          setAmount('');
          setDescription('');
          setCategoryId('');
        },
      },
    );
  }

  const selectClass = 'h-11 rounded-input border border-line-2 bg-field px-3 text-[16px] text-ink';

  return (
    <Card>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Amount">
            <TextInput
              inputMode="decimal"
              placeholder="12,50"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
          <Field label="Date">
            <TextInput
              type="date"
              value={occurredOn}
              onChange={(e) => setOccurredOn(e.target.value)}
            />
          </Field>
          <Field label="Type">
            <select
              className={selectClass}
              value={kind}
              onChange={(e) => setKind(e.target.value as Kind)}
            >
              <option value="expense">Expense</option>
              <option value="income">Income</option>
            </select>
          </Field>
          <Field label="Category">
            <select
              className={selectClass}
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
            >
              <option value="">None</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Description">
          <TextInput
            placeholder="Lunch at Hesburger"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        {error && <p className="text-[13px] text-over">{error}</p>}
        <div className="flex justify-end">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? 'Saving…' : 'Save transaction'}
          </Button>
        </div>
      </form>
    </Card>
  );
}
