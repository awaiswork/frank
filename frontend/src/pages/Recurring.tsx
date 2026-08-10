import { useState, type FormEvent } from 'react';
import {
  useAccounts,
  useCategories,
  useCreateRecurring,
  useDeleteRecurring,
  useRecurring,
  useUpdateRecurring,
} from '../api/hooks';
import type { Cadence, Kind, Recurring as RecurringItem } from '../api/types';
import { Money } from '../components/Money';
import { Button, Card, EmptyState, Field, SectionLabel, TextInput } from '../components/ui';
import { todayISO } from '../lib/date';
import { parseAmountToCents } from '../lib/money';

const CADENCES: { value: Cadence; label: string }[] = [
  { value: 'weekly', label: 'Every week' },
  { value: 'monthly', label: 'Every month' },
  { value: 'yearly', label: 'Every year' },
];

const CADENCE_LABEL: Record<Cadence, string> = {
  weekly: 'weekly',
  monthly: 'monthly',
  yearly: 'yearly',
};

function whenLabel(iso: string | null): string {
  if (!iso) return 'finished';
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });
}

/**
 * The things that repeat.
 *
 * A template is a schedule, not money. Occurrences become ordinary transactions on the
 * day they fall due and not a moment earlier, so nothing here counts toward what you
 * have spent until it actually has been — a rent payment due next month is a plan.
 */
export function Recurring() {
  const items = useRecurring();
  const [adding, setAdding] = useState(false);

  const rows = items.data ?? [];
  const income = rows.filter((r) => r.kind === 'income');
  const expense = rows.filter((r) => r.kind === 'expense');

  return (
    <section className="animate-fade-up mx-auto flex max-w-[640px] flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-[24px] font-semibold tracking-[-0.02em]">Repeating</h1>
          <p className="mt-1 text-[14.5px] text-muted">
            Rent, salary, subscriptions. Frankly logs them on the day, so you don't have to.
          </p>
        </div>
        {rows.length > 0 && !adding && (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            Add one
          </Button>
        )}
      </div>

      {adding && <AddRecurring onDone={() => setAdding(false)} />}

      {!items.isPending && rows.length === 0 && !adding && (
        <>
          <EmptyState
            title="Nothing repeating yet"
            hint="Add the things that turn up every month and they'll log themselves."
          />
          <Button onClick={() => setAdding(true)}>Add your first one</Button>
        </>
      )}

      <Group label="Going out" items={expense} />
      <Group label="Coming in" items={income} />
    </section>
  );
}

function Group({ label, items }: { label: string; items: RecurringItem[] }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-2.5">
      <SectionLabel>{label}</SectionLabel>
      <Card className="flex flex-col gap-4">
        {items.map((item, i) => (
          <Row key={item.id} item={item} last={i === items.length - 1} />
        ))}
      </Card>
    </div>
  );
}

function Row({ item, last }: { item: RecurringItem; last: boolean }) {
  const update = useUpdateRecurring();
  const remove = useDeleteRecurring();
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center justify-between gap-4 text-left"
      >
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink">{item.name}</div>
          <div className="mt-0.5 text-[13px] text-muted">
            {CADENCE_LABEL[item.cadence]} · next {whenLabel(item.next_on)}
          </div>
        </div>
        <span className="num shrink-0 text-[16px] font-semibold">
          <Money cents={item.amount_cents} tone={item.kind === 'income' ? 'go' : 'default'} />
        </span>
      </button>

      {open && (
        <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-muted">
          <span>Since {whenLabel(item.start_on)}</span>
          <span className="grow" />
          <Button variant="ghost" onClick={() => update.mutate({ id: item.id, archived: true })}>
            Stop
          </Button>
          {/* Deleting removes the schedule, not the money it already logged — those are
              real transactions and the rent really was paid. */}
          <Button variant="ghost" onClick={() => remove.mutate(item.id)}>
            Delete
          </Button>
        </div>
      )}
      {!last && <div className="h-px bg-line" />}
    </div>
  );
}

function AddRecurring({ onDone }: { onDone: () => void }) {
  const create = useCreateRecurring();
  const categories = useCategories();
  const accounts = useAccounts();

  const [name, setName] = useState('');
  const [kind, setKind] = useState<Kind>('expense');
  const [amount, setAmount] = useState('');
  const [cadence, setCadence] = useState<Cadence>('monthly');
  const [startOn, setStartOn] = useState(todayISO());
  const [categoryId, setCategoryId] = useState('');
  const [accountId, setAccountId] = useState('');

  const cents = parseAmountToCents(amount);
  const usable = (accounts.data?.accounts ?? []).filter(
    (a) => a.archived_at === null && a.type !== 'person',
  );
  const pickable = (categories.data ?? []).filter((c) => c.kind === kind);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || cents == null || cents <= 0) return;
    create.mutate(
      {
        name: name.trim(),
        kind,
        amount_cents: cents,
        cadence,
        start_on: startOn,
        category_id: categoryId || null,
        account_id: accountId || null,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex self-start rounded-full bg-inset p-1">
          {(['expense', 'income'] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => {
                setKind(k);
                setCategoryId('');
              }}
              aria-pressed={kind === k}
              className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold capitalize transition-colors ${
                kind === k ? 'bg-surface text-ink' : 'text-muted hover:text-ink-2'
              }`}
            >
              {k === 'expense' ? 'Going out' : 'Coming in'}
            </button>
          ))}
        </div>

        <Field label="What is it?">
          <TextInput
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={kind === 'income' ? 'Salary' : 'Rent'}
          />
        </Field>

        <Field label="How much?">
          <TextInput
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="800"
          />
        </Field>

        <Field label="How often?">
          <select
            value={cadence}
            onChange={(e) => setCadence(e.target.value as Cadence)}
            aria-label="How often"
            className="h-11 w-full rounded-input border border-line-2 bg-field px-2.5 text-[16px] text-ink"
          >
            {CADENCES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Starting">
          <TextInput type="date" value={startOn} onChange={(e) => setStartOn(e.target.value)} />
        </Field>

        {pickable.length > 0 && (
          <Field label="Category">
            <select
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              aria-label="Category"
              className="h-11 w-full rounded-input border border-line-2 bg-field px-2.5 text-[16px] text-ink"
            >
              <option value="">No category</option>
              {pickable.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        )}

        {usable.length > 0 && (
          <Field label={kind === 'income' ? 'Into' : 'Out of'}>
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              aria-label="Account"
              className="h-11 w-full rounded-input border border-line-2 bg-field px-2.5 text-[16px] text-ink"
            >
              <option value="">No account</option>
              {usable.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
        )}

        {/* The honest bit: this is a schedule, and it does not spend anything today. */}
        <p className="text-[13px] text-muted">
          Frankly logs each one on the day it's due — never before, so nothing counts as spent until
          it has been. Backdating the start date logs the ones already past.
        </p>

        <div className="flex items-center gap-2.5">
          <Button type="submit" disabled={!name.trim() || cents == null || create.isPending}>
            {create.isPending ? 'Saving…' : 'Add it'}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
        {create.isError && <p className="text-[13px] text-over">Couldn't save — try again.</p>}
      </form>
    </Card>
  );
}
