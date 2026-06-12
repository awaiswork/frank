import { useMemo, useState } from 'react';
import { useCategories, useDeleteTransaction, useTransactions } from '../api/hooks';
import type { Category, Transaction } from '../api/types';
import { CategoryAvatar } from '../components/CategoryAvatar';
import { AiBadge } from '../components/bits';
import { Money } from '../components/Money';
import { Card } from '../components/ui';
import { currentMonth, monthLabel, shiftMonth } from '../lib/date';
import { formatMoney } from '../lib/money';

function dayHeading(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const that = new Date(y, m - 1, d);
  const now = new Date();
  const diff = Math.round(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - that.getTime()) /
      86_400_000,
  );
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return that.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'long' });
}

export function Transactions() {
  const [month, setMonth] = useState(currentMonth());
  const [q, setQ] = useState('');
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const categories = useCategories();
  const transactions = useTransactions({
    month,
    q: q.trim() || undefined,
    categoryId: categoryId ?? undefined,
  });

  const catById = useMemo(() => {
    const map = new Map<string, Category>();
    for (const c of categories.data ?? []) map.set(c.id, c);
    return map;
  }, [categories.data]);

  const groups = useMemo(() => {
    const map = new Map<string, Transaction[]>();
    for (const t of transactions.data ?? []) {
      const arr = map.get(t.occurred_on) ?? [];
      arr.push(t);
      map.set(t.occurred_on, arr);
    }
    return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [transactions.data]);

  const expenseCats = (categories.data ?? []).filter((c) => c.kind === 'expense');

  return (
    <section className="animate-fade-up mx-auto flex max-w-[760px] flex-col gap-[18px]">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            aria-label="Previous month"
            onClick={() => setMonth(shiftMonth(month, -1))}
            className="grid h-[34px] w-[34px] place-items-center rounded-[9px] border border-line-2 bg-surface text-ink-2 hover:text-ink"
          >
            ‹
          </button>
          <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em] whitespace-nowrap">
            {monthLabel(month)}
          </h1>
          <button
            aria-label="Next month"
            onClick={() => setMonth(shiftMonth(month, 1))}
            className="grid h-[34px] w-[34px] place-items-center rounded-[9px] border border-line-2 bg-surface text-ink-2 hover:text-ink"
          >
            ›
          </button>
        </div>
        <div className="flex w-[230px] items-center gap-2.5 rounded-[11px] border border-line-2 bg-surface px-3 py-2">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--muted)"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search"
            className="min-w-0 flex-1 bg-transparent text-[14px] text-ink placeholder:text-faint focus:outline-none"
          />
        </div>
      </div>

      {/* Category chips */}
      <div className="flex flex-wrap gap-2">
        <Chip label="All" active={categoryId === null} onClick={() => setCategoryId(null)} />
        {expenseCats.map((c) => (
          <Chip
            key={c.id}
            label={c.name}
            active={categoryId === c.id}
            onClick={() => setCategoryId(c.id)}
          />
        ))}
      </div>

      {groups.length === 0 ? (
        <Card className="px-6 py-12 text-center">
          <div className="text-[16px] font-semibold text-ink">Nothing here</div>
          <div className="mt-1 text-[14px] text-muted">
            {q || categoryId ? 'No transactions match that.' : 'Capture your first one from Home.'}
          </div>
        </Card>
      ) : (
        <div className="flex flex-col gap-[22px]">
          {groups.map(([day, items]) => {
            const net = items.reduce(
              (a, t) => a + (t.kind === 'income' ? t.amount_cents : -t.amount_cents),
              0,
            );
            return (
              <div key={day}>
                <div className="mb-2 flex items-center justify-between px-0.5">
                  <span className="text-[12.5px] font-bold tracking-[0.06em] text-muted uppercase">
                    {dayHeading(day)}
                  </span>
                  <span className="num text-[12.5px] font-semibold text-muted">
                    {formatMoney(net, { signed: true })}
                  </span>
                </div>
                <Card className="p-0">
                  {items.map((t) => (
                    <Row
                      key={t.id}
                      tx={t}
                      category={t.category_id ? (catById.get(t.category_id) ?? null) : null}
                    />
                  ))}
                </Card>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3.5 py-[7px] text-[13px] font-semibold whitespace-nowrap transition-colors ${
        active
          ? 'border-ink bg-ink text-paper'
          : 'border-line-2 bg-surface text-ink-2 hover:text-ink'
      }`}
    >
      {label}
    </button>
  );
}

function Row({ tx, category }: { tx: Transaction; category: Category | null }) {
  const del = useDeleteTransaction();
  const income = tx.kind === 'income';
  const label = tx.merchant ?? tx.description;
  return (
    <div className="group flex items-center gap-[13px] border-b border-line px-4 py-[13px] last:border-0">
      <CategoryAvatar
        initial={label.charAt(0).toUpperCase()}
        category={category?.name ?? null}
        size={36}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-[7px] text-[14.5px] font-semibold text-ink">
          <span className="truncate">{label}</span>
          {tx.source === 'nl_parse' && <AiBadge />}
        </div>
        <div className="truncate text-[12.5px] text-muted">{category?.name ?? 'Uncategorised'}</div>
      </div>
      <button
        type="button"
        aria-label="Delete transaction"
        disabled={del.isPending}
        onClick={() => del.mutate(tx.id)}
        className="text-[16px] leading-none text-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-over disabled:opacity-40"
      >
        ×
      </button>
      <Money
        cents={income ? tx.amount_cents : -tx.amount_cents}
        signed={income}
        tone={income ? 'go' : 'default'}
        className="!text-[15.5px] font-semibold"
      />
    </div>
  );
}
