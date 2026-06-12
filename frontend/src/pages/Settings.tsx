import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCategories, useTransactions, useUpdateMe } from '../api/hooks';
import type { Category, Transaction, User } from '../api/types';
import { useAuth } from '../auth/useAuth';
import { CategoryAvatar } from '../components/CategoryAvatar';
import { Button, Card, SectionLabel, TextInput } from '../components/ui';
import { currentMonth, monthLabel } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';

export function Settings() {
  const { user, setUser, logout } = useAuth();
  const categories = useCategories();
  const navigate = useNavigate();

  return (
    <section className="animate-fade-up mx-auto flex max-w-[640px] flex-col gap-6">
      <div>
        <h1 className="font-display text-[24px] font-semibold tracking-[-0.02em]">Settings</h1>
        <p className="mt-1 text-[14.5px] text-muted">
          Your money, your categories, your data — all in one place.
        </p>
      </div>

      <Block label="Money">
        <Card className="flex flex-col gap-5">
          <Row label="Currency" hint="More currencies are on the way.">
            <span className="num text-[15px] font-semibold text-ink-2">
              {user?.currency ?? 'EUR'} · €
            </span>
          </Row>
          <div className="h-px bg-line" />
          <IncomeRow incomeCents={user?.monthly_income_cents ?? null} onSaved={setUser} />
        </Card>
      </Block>

      <Block label="Categories">
        <Card className="p-0">
          {categories.data?.length ? (
            categories.data.map((c, i) => (
              <CategoryRow key={c.id} category={c} last={i === categories.data!.length - 1} />
            ))
          ) : (
            <p className="px-5 py-6 text-[14px] text-muted">Loading your categories…</p>
          )}
        </Card>
      </Block>

      <Block label="Your data">
        <Card className="flex flex-col gap-4">
          <ExportRow />
          <div className="h-px bg-line" />
          <Row label="Set-up walkthrough" hint="Re-run the welcome flow any time.">
            <Button variant="secondary" onClick={() => navigate('/onboarding')}>
              Replay setup
            </Button>
          </Row>
        </Card>
      </Block>

      <Block label="Account">
        <Card className="flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-muted">Signed in as</div>
            <div className="truncate text-[15px] font-semibold text-ink">{user?.email}</div>
          </div>
          <Button variant="secondary" onClick={logout}>
            Sign out
          </Button>
        </Card>
      </Block>
    </section>
  );
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <SectionLabel>{label}</SectionLabel>
      {children}
    </div>
  );
}

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="text-[15px] font-semibold text-ink">{label}</div>
        {hint && <div className="mt-0.5 text-[13px] text-muted">{hint}</div>}
      </div>
      {children}
    </div>
  );
}

function IncomeRow({
  incomeCents,
  onSaved,
}: {
  incomeCents: number | null;
  onSaved: (user: User) => void;
}) {
  const update = useUpdateMe();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(incomeCents != null ? String(incomeCents / 100) : '');

  function save(e: FormEvent) {
    e.preventDefault();
    const cents = parseAmountToCents(value);
    if (cents == null) return;
    update.mutate(
      { monthly_income_cents: cents },
      {
        onSuccess: (u) => {
          onSaved(u);
          setEditing(false);
        },
      },
    );
  }

  if (!editing) {
    return (
      <Row label="Monthly income" hint="Frank uses this to work out what's safe to spend.">
        <div className="flex items-center gap-3">
          <span className="num text-[15px] font-semibold text-ink">
            {incomeCents != null ? formatMoney(incomeCents) : 'Not set'}
          </span>
          <Button
            variant="secondary"
            onClick={() => {
              setValue(incomeCents != null ? String(incomeCents / 100) : '');
              setEditing(true);
            }}
          >
            Edit
          </Button>
        </div>
      </Row>
    );
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-2.5">
      <div className="text-[15px] font-semibold text-ink">Monthly income</div>
      <div className="flex items-center gap-2.5">
        <div className="relative flex-1">
          <span className="absolute top-1/2 left-3 -translate-y-1/2 text-[15px] text-muted">€</span>
          <TextInput
            autoFocus
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="3200"
            className="pl-7"
          />
        </div>
        <Button type="submit" disabled={parseAmountToCents(value) == null || update.isPending}>
          {update.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
      {update.isError && <p className="text-[13px] text-over">Couldn't save — try again.</p>}
    </form>
  );
}

function CategoryRow({ category, last }: { category: Category; last: boolean }) {
  return (
    <div className={`flex items-center gap-3 px-5 py-3.5 ${last ? '' : 'border-b border-line'}`}>
      <CategoryAvatar initial={category.name.charAt(0)} category={category.name} size={34} />
      <span className="flex-1 text-[14.5px] font-medium text-ink">{category.name}</span>
      <span className="rounded-full bg-inset px-2.5 py-1 text-[11.5px] font-semibold tracking-[0.06em] text-muted uppercase">
        {category.kind}
      </span>
    </div>
  );
}

function ExportRow() {
  const month = currentMonth();
  const transactions = useTransactions({ month });
  const categories = useCategories();
  const rows = transactions.data ?? [];

  function exportCsv() {
    const names = new Map((categories.data ?? []).map((c) => [c.id, c.name]));
    const csv = toCsv(rows, names);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `frank-${month}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Row label="Export this month" hint={`${rows.length} transactions in ${monthLabel(month)}.`}>
      <Button variant="secondary" disabled={rows.length === 0} onClick={exportCsv}>
        Export CSV
      </Button>
    </Row>
  );
}

function toCsv(rows: Transaction[], names: Map<string, string>): string {
  const head = ['Date', 'Description', 'Merchant', 'Category', 'Kind', 'Amount (€)'];
  const esc = (v: string) => `"${v.replace(/"/g, '""')}"`;
  const lines = rows.map((t) =>
    [
      t.occurred_on,
      esc(t.description),
      esc(t.merchant ?? ''),
      esc(t.category_id ? (names.get(t.category_id) ?? '') : ''),
      t.kind,
      (t.amount_cents / 100).toFixed(2),
    ].join(','),
  );
  return [head.join(','), ...lines].join('\n');
}
