import { useMemo, useState } from 'react';
import { useCategories, useDeleteTransaction, useTransactions } from '../api/hooks';
import type { Category } from '../api/types';
import { Capture } from '../components/Capture';
import { Money } from '../components/Money';
import { MonthSwitcher } from '../components/MonthSwitcher';
import { Card, EmptyState, SectionLabel, TextInput } from '../components/ui';
import { currentMonth } from '../lib/date';

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

      <Capture />

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <SectionLabel>This month</SectionLabel>
          <TextInput
            className="h-9 max-w-50 text-[14px]"
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
            hint={q ? 'Try a different search.' : 'Capture your first one above.'}
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
