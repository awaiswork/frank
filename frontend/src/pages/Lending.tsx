import { useMemo, useState, type FormEvent } from 'react';
import { useAccounts, useCreateTransaction, useLend } from '../api/hooks';
import type { Account } from '../api/types';
import { Money } from '../components/Money';
import { Button, Card, EmptyState, Field, SectionLabel, TextInput } from '../components/ui';
import { todayISO } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';

/**
 * Who owes you, and who you owe.
 *
 * Every action here writes an ordinary transfer between one of your accounts and the
 * person's, so nothing on this screen can reach a spending report or change what you
 * are worth — lending moves money, it does not lose it. The person's balance *is* the
 * outstanding amount, and its sign is the direction.
 */
export function Lending() {
  const accounts = useAccounts();
  const [lending, setLending] = useState(false);

  const people = useMemo(
    () => (accounts.data?.accounts ?? []).filter((a) => a.type === 'person'),
    [accounts.data],
  );
  const spendable = useMemo(
    () => (accounts.data?.accounts ?? []).filter((a) => a.type !== 'person'),
    [accounts.data],
  );

  const owesYou = people.filter((p) => p.balance_cents > 0);
  const youOwe = people.filter((p) => p.balance_cents < 0);
  const settled = people.filter((p) => p.balance_cents === 0);

  return (
    <section className="animate-fade-up mx-auto flex max-w-[640px] flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-[24px] font-semibold tracking-[-0.02em]">Lending</h1>
          <p className="mt-1 text-[14.5px] text-muted">
            Money that's yours but isn't with you, and money that isn't yours but is.
          </p>
        </div>
        {spendable.length > 0 && !lending && (
          <Button variant="secondary" onClick={() => setLending(true)}>
            Record one
          </Button>
        )}
      </div>

      {spendable.length === 0 ? (
        <EmptyState
          title="Add an account first"
          hint="Lending moves money out of somewhere, so Frankly needs to know where from."
        />
      ) : lending ? (
        <LendForm accounts={spendable} onDone={() => setLending(false)} />
      ) : null}

      {!accounts.isPending && people.length === 0 && !lending && spendable.length > 0 && (
        <EmptyState
          title="Nothing outstanding"
          hint="Lent someone a tenner? Record it and Frankly will keep track of what comes back."
        />
      )}

      <PeopleGroup label="Owes you" people={owesYou} accounts={spendable} />
      <PeopleGroup label="You owe" people={youOwe} accounts={spendable} />

      {settled.length > 0 && (
        <p className="text-[13px] text-muted">
          {settled.length} settled {settled.length === 1 ? 'person' : 'people'} —{' '}
          {settled.map((p) => p.name).join(', ')}. Archive them on Wealth when you're done.
        </p>
      )}
    </section>
  );
}

function PeopleGroup({
  label,
  people,
  accounts,
}: {
  label: string;
  people: Account[];
  accounts: Account[];
}) {
  if (!people.length) return null;
  return (
    <div className="flex flex-col gap-2.5">
      <SectionLabel>{label}</SectionLabel>
      <Card className="flex flex-col gap-4">
        {people.map((person, i) => (
          <PersonRow
            key={person.id}
            person={person}
            accounts={accounts}
            last={i === people.length - 1}
          />
        ))}
      </Card>
    </div>
  );
}

function PersonRow({
  person,
  accounts,
  last,
}: {
  person: Account;
  accounts: Account[];
  last: boolean;
}) {
  const [settling, setSettling] = useState(false);
  const outstanding = Math.abs(person.balance_cents);
  const theyOweYou = person.balance_cents > 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        {/* No "owes you" line under the name: the section heading above already says
            the direction, and repeating it here wrapped to two lines on a 320px row
            for no information at all. */}
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink">{person.name}</div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="num text-[16px] font-semibold">
            <Money cents={outstanding} tone={theyOweYou ? 'go' : 'over'} />
          </span>
          <Button variant="secondary" onClick={() => setSettling((v) => !v)}>
            {theyOweYou ? 'Paid back' : 'Pay back'}
          </Button>
        </div>
      </div>

      {settling && <Settle person={person} accounts={accounts} onDone={() => setSettling(false)} />}
      {!last && <div className="h-px bg-line" />}
    </div>
  );
}

function Settle({
  person,
  accounts,
  onDone,
}: {
  person: Account;
  accounts: Account[];
  onDone: () => void;
}) {
  const create = useCreateTransaction();
  const outstanding = Math.abs(person.balance_cents);
  const theyOweYou = person.balance_cents > 0;
  // Prefilled with the whole balance, because settling up in full is the common case
  // and a partial repayment is one edit away.
  const [amount, setAmount] = useState(String(outstanding / 100).replace('.', ','));
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? '');

  const cents = parseAmountToCents(amount);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (cents == null || cents <= 0 || !accountId) return;
    create.mutate(
      {
        kind: 'transfer',
        amount_cents: cents,
        // Repayment runs the opposite way to the original: money comes back from them
        // when they owed you, and goes out to them when you owed.
        account_id: theyOweYou ? person.id : accountId,
        counter_account_id: theyOweYou ? accountId : person.id,
        description: theyOweYou ? `${person.name} paid back` : `Paid back ${person.name}`,
        occurred_on: todayISO(),
      },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2.5 rounded-input bg-inset p-3">
      <div className="flex flex-wrap items-end gap-2.5">
        <div className="min-w-0 flex-1 basis-[120px]">
          <Field label="How much?">
            <TextInput
              autoFocus
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
        </div>
        <label className="flex min-w-0 flex-1 basis-[140px] flex-col gap-1.5 text-[13px] text-muted">
          {theyOweYou ? 'into' : 'from'}
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            aria-label="Account"
            className="h-11 rounded-input border border-line-2 bg-field px-2.5 text-[14px] text-ink"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {cents != null && cents > outstanding && (
        <p className="text-[13px] text-muted">
          That's more than the {formatMoney(outstanding)} outstanding — the rest will flip the
          balance the other way.
        </p>
      )}
      <div className="flex items-center gap-2.5">
        <Button type="submit" disabled={cents == null || cents <= 0 || create.isPending}>
          {create.isPending ? 'Saving…' : 'Record it'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {create.isError && <p className="text-[13px] text-over">Couldn't save — try again.</p>}
    </form>
  );
}

function LendForm({ accounts, onDone }: { accounts: Account[]; onDone: () => void }) {
  const lend = useLend();
  const [person, setPerson] = useState('');
  const [amount, setAmount] = useState('');
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? '');
  const [borrowing, setBorrowing] = useState(false);

  const cents = parseAmountToCents(amount);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!person.trim() || cents == null || cents <= 0 || !accountId) return;
    lend.mutate(
      { person: person.trim(), amount_cents: cents, account_id: accountId, borrowing },
      { onSuccess: onDone },
    );
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex rounded-full bg-inset p-1 self-start">
          {[
            { value: false, label: 'I lent' },
            { value: true, label: 'I borrowed' },
          ].map((option) => (
            <button
              key={option.label}
              type="button"
              onClick={() => setBorrowing(option.value)}
              aria-pressed={borrowing === option.value}
              className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
                borrowing === option.value ? 'bg-surface text-ink' : 'text-muted hover:text-ink-2'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        <Field label="Who?">
          <TextInput
            autoFocus
            value={person}
            onChange={(e) => setPerson(e.target.value)}
            placeholder="Sam"
          />
        </Field>

        <Field label="How much?">
          <TextInput
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="50"
          />
        </Field>

        <label className="flex flex-col gap-1.5 text-[13px] text-muted">
          {borrowing ? 'into' : 'out of'}
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            aria-label="Account"
            className="h-11 rounded-input border border-line-2 bg-field px-2.5 text-[14px] text-ink"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>

        {/* Says the thing people worry about: this is not spending, and you have not
            lost the money — it is just somewhere else. */}
        <p className="text-[13px] text-muted">
          {borrowing
            ? "Frankly records what you owe. It won't count as income."
            : "Frankly records what you're owed. It won't count as spending."}
        </p>

        <div className="flex items-center gap-2.5">
          <Button
            type="submit"
            disabled={!person.trim() || cents == null || cents <= 0 || lend.isPending}
          >
            {lend.isPending ? 'Saving…' : 'Record it'}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
        {lend.isError && (
          <p className="text-[13px] text-over">
            Couldn't save — you may already have an account with that name.
          </p>
        )}
      </form>
    </Card>
  );
}
