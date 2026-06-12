import { useState, type FormEvent } from 'react';
import { useContribute, useCreateGoal, useGoals, useUpdateGoal } from '../api/hooks';
import type { Goal } from '../api/types';
import { Money } from '../components/Money';
import { Button, Card, EmptyState, Field, SectionLabel, TextInput } from '../components/ui';
import { parseAmountToCents } from '../lib/money';

export function Goals() {
  const goals = useGoals();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-[22px] font-bold text-ink">Goals</h1>

      <NewGoal />

      <section className="flex flex-col gap-3">
        <SectionLabel>Active goals</SectionLabel>
        {goals.data && goals.data.length > 0 ? (
          <div className="flex flex-col gap-3">
            {goals.data.map((g) => (
              <GoalCard key={g.id} goal={g} />
            ))}
          </div>
        ) : (
          <EmptyState title="No goals yet" hint="Name something you're saving for above." />
        )}
      </section>
    </div>
  );
}

function GoalCard({ goal }: { goal: Goal }) {
  const contribute = useContribute();
  const update = useUpdateGoal();
  const [amount, setAmount] = useState('');
  const funded = goal.progress_fraction >= 1;
  const pct = Math.min(Math.max(goal.progress_fraction, 0), 1) * 100;

  function add() {
    const cents = parseAmountToCents(amount);
    if (cents === null) return;
    contribute.mutate({ id: goal.id, amountCents: cents }, { onSuccess: () => setAmount('') });
  }

  return (
    <Card
      className="flex flex-col gap-3"
      {...(funded ? { style: { boxShadow: 'var(--shadow)', borderColor: 'var(--go)' } } : {})}
    >
      <div className="flex items-baseline justify-between">
        <span className="font-display text-[18px] font-semibold text-ink">{goal.name}</span>
        <span className="text-[13px] text-muted">
          <Money cents={goal.contributed_cents} /> /{' '}
          <Money cents={goal.target_cents} tone="muted" />
        </span>
      </div>

      <div className="h-2 w-full overflow-hidden rounded-full bg-inset">
        <div
          className="animate-bar-grow h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: funded ? 'var(--go)' : 'var(--cat-savings, var(--wait))',
          }}
        />
      </div>

      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] text-muted">
          {funded ? (
            <span className="font-semibold text-go">Funded</span>
          ) : (
            <>
              {Math.round(goal.progress_fraction * 100)}% saved
              {goal.due_date ? ` · by ${goal.due_date}` : ''}
            </>
          )}
        </span>
        <div className="flex items-center gap-2">
          <TextInput
            inputMode="decimal"
            placeholder="Add €"
            aria-label={`Contribute to ${goal.name}`}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="h-9 w-24 text-[14px]"
          />
          <Button
            variant="secondary"
            className="h-9 px-4 text-[13px]"
            disabled={contribute.isPending}
            onClick={add}
          >
            Add
          </Button>
          <button
            type="button"
            aria-label={`Archive ${goal.name}`}
            disabled={update.isPending}
            onClick={() => update.mutate({ id: goal.id, archived: true })}
            className="text-[13px] text-faint hover:text-ink-2 disabled:opacity-40"
          >
            Archive
          </button>
        </div>
      </div>
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
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
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
