import { useState, type FormEvent } from 'react';
import { useContribute, useCreateGoal, useGoals, useUpdateGoal } from '../api/hooks';
import type { Goal } from '../api/types';
import { CategoryAvatar } from '../components/CategoryAvatar';
import { FrankCallout } from '../components/bits';
import { Button, Card, EmptyState, Field, SectionLabel, TextInput } from '../components/ui';
import { formatMoney, moneyParts, parseAmountToCents } from '../lib/money';

export function Goals() {
  const goals = useGoals();

  return (
    <section className="animate-fade-up mx-auto flex max-w-[760px] flex-col gap-5">
      <div>
        <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em]">Savings goals</h1>
        <p className="mt-1 text-[14px] text-muted">
          Progress comes from what you actually put in, not what you hope to.
        </p>
      </div>

      <NewGoal />

      {goals.data && goals.data.length > 0 ? (
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          {goals.data.map((g) => (
            <GoalCard key={g.id} goal={g} />
          ))}
        </div>
      ) : (
        <EmptyState title="No goals yet" hint="Name something you're saving for above." />
      )}
    </section>
  );
}

function GoalCard({ goal }: { goal: Goal }) {
  const contribute = useContribute();
  const update = useUpdateGoal();
  const [amount, setAmount] = useState('');
  const reached = goal.progress_fraction >= 1;
  const pct = Math.min(Math.max(goal.progress_fraction, 0), 1) * 100;
  const saved = moneyParts(goal.contributed_cents);

  function add() {
    const cents = parseAmountToCents(amount);
    if (cents === null) return;
    contribute.mutate({ id: goal.id, amountCents: cents }, { onSuccess: () => setAmount('') });
  }

  return (
    <Card
      className="flex flex-col p-5"
      {...(reached ? { style: { boxShadow: 'var(--shadow)', borderColor: 'var(--go)' } } : {})}
    >
      <div className="flex items-center gap-3">
        <CategoryAvatar initial={goal.name.charAt(0).toUpperCase()} category="Savings" size={42} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[16px] font-semibold text-ink">{goal.name}</div>
          <div className="truncate text-[12.5px] text-muted">
            {goal.due_date ? `by ${goal.due_date}` : 'no deadline'}
          </div>
        </div>
        <button
          type="button"
          aria-label={`Archive ${goal.name}`}
          disabled={update.isPending}
          onClick={() => update.mutate({ id: goal.id, archived: true })}
          className="text-[12px] text-faint hover:text-ink-2 disabled:opacity-40"
        >
          Archive
        </button>
      </div>

      <div className="num mt-[18px] flex items-baseline gap-[5px]">
        <span className="text-[30px] font-semibold tracking-[-0.02em]">{saved.euros}</span>
        <span className="text-[16px] text-muted">/ {formatMoney(goal.target_cents)}</span>
      </div>

      <div className="mt-3 h-2 overflow-hidden rounded-full bg-inset">
        <div
          className="animate-bar-grow h-full rounded-full"
          style={{ width: `${pct}%`, background: reached ? 'var(--go)' : 'var(--cat-savings)' }}
        />
      </div>

      <div
        className="mt-2.5 flex items-center gap-[7px] text-[13px] font-semibold"
        style={{ color: reached ? 'var(--go)' : 'var(--muted)' }}
      >
        {reached && (
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
        )}
        {reached ? 'Funded' : `${Math.round(goal.progress_fraction * 100)}% saved`}
      </div>

      <div className="min-h-2 flex-1" />

      {reached ? (
        <div className="mt-4">
          <FrankCallout tone="go">That's done. Move the money over when you're ready.</FrankCallout>
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-2">
          <TextInput
            inputMode="decimal"
            placeholder="Add €"
            aria-label={`Contribute to ${goal.name}`}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="h-10 flex-1 text-[14px]"
          />
          <Button className="h-10 px-4" disabled={contribute.isPending} onClick={add}>
            Add
          </Button>
        </div>
      )}
    </Card>
  );
}

function NewGoal() {
  const create = useCreateGoal();
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [due, setDue] = useState('');
  const [error, setError] = useState<string | null>(null);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const cents = parseAmountToCents(target);
    if (!name.trim()) {
      setError('Give your goal a name');
      return;
    }
    if (cents === null) {
      setError('Enter a target like 1 200');
      return;
    }
    setError(null);
    create.mutate(
      { name: name.trim(), target_cents: cents, due_date: due || null },
      {
        onSuccess: () => {
          setName('');
          setTarget('');
          setDue('');
        },
      },
    );
  }

  return (
    <Card>
      <SectionLabel>New goal</SectionLabel>
      <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Goal">
            <TextInput
              placeholder="Trip to Lisbon"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Target">
            <TextInput
              inputMode="decimal"
              placeholder="1 200"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </Field>
          <Field label="Due (optional)">
            <TextInput type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
        </div>
        {error && <p className="text-[13px] text-over">{error}</p>}
        <div className="flex justify-end">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? 'Adding…' : 'Add goal'}
          </Button>
        </div>
      </form>
    </Card>
  );
}
