import { useState, type FormEvent } from 'react';
import {
  useAccounts,
  useCreateAccount,
  useDeleteAccount,
  useReconcileAccount,
  useUpdateAccount,
} from '../api/hooks';
import type { Account, AccountType } from '../api/types';
import { Button, Card, EmptyState, Field, SectionLabel, TextInput } from '../components/ui';
import { Money } from '../components/Money';
import { todayISO } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';

/** Ledger accounts only — a car or a flat has no entries to sum, so it isn't one. */
const TYPES: { value: AccountType; label: string; hint: string }[] = [
  { value: 'current', label: 'Current', hint: 'Everyday spending' },
  { value: 'savings', label: 'Savings', hint: 'Money set aside' },
  { value: 'cash', label: 'Cash', hint: 'What you carry' },
  { value: 'liability', label: 'Owed', hint: 'Credit card, overdraft' },
];

type GroupKey = 'liquid' | 'owesYou' | 'youOwe' | 'owed';

const GROUP_LABELS: Record<GroupKey, string> = {
  liquid: 'Liquid',
  owesYou: 'Owes you',
  youOwe: 'You owe',
  owed: 'Owed',
};

const GROUP_ORDER: GroupKey[] = ['liquid', 'owesYou', 'youOwe', 'owed'];

/**
 * Which section an account belongs in.
 *
 * A `switch` with a `never` fallthrough rather than a list of types per group. The
 * list version compiled perfectly happily when `person` was added and rendered those
 * accounts *nowhere* — while still counting them in the total, so the rows would have
 * stopped adding up to the figure above them with nothing on screen to say why. This
 * shape stops compiling until a new type is placed.
 *
 * People are grouped by the sign of what they owe, not by a label chosen when the
 * account was made: a balance cannot go stale and a label can.
 */
function groupOf(account: Account): GroupKey {
  switch (account.type) {
    case 'current':
    case 'savings':
    case 'cash':
      return 'liquid';
    case 'liability':
      return 'owed';
    case 'person':
      return account.balance_cents < 0 ? 'youOwe' : 'owesYou';
    default: {
      const unreachable: never = account.type;
      return unreachable;
    }
  }
}

export function Wealth() {
  const accounts = useAccounts();
  const [adding, setAdding] = useState(false);

  const rows = accounts.data?.accounts ?? [];
  const total = accounts.data?.total_cents ?? 0;
  const startsOn = accounts.data?.ledger_starts_on ?? null;

  return (
    <section className="animate-fade-up mx-auto flex max-w-[640px] flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-[24px] font-semibold tracking-[-0.02em]">Wealth</h1>
          <p className="mt-1 text-[14.5px] text-muted">
            What you have, and what you owe. A weekly look, not a daily one.
          </p>
        </div>
        {rows.length > 0 && !adding && (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            Add account
          </Button>
        )}
      </div>

      {rows.length > 0 && (
        <Card className="flex flex-col gap-1.5">
          <SectionLabel>Total</SectionLabel>
          <div className="num text-[34px] font-semibold tracking-[-0.02em]">
            <Money cents={total} />
          </div>
          {startsOn && (
            // Never let the total read as though it covers all the history the app
            // holds. Anything logged before the ledger opened is spending, not balance.
            <p className="text-[13px] text-muted">
              Balances count entries from{' '}
              {new Date(startsOn).toLocaleDateString('en-GB', {
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })}
              .
            </p>
          )}
        </Card>
      )}

      {adding && <AddAccount onDone={() => setAdding(false)} />}

      {accounts.isPending ? (
        <p className="text-[14px] text-muted">Loading your accounts…</p>
      ) : rows.length === 0 && !adding ? (
        <EmptyState
          title="No accounts yet"
          hint="Add where your money actually sits, and Frankly can keep a running balance."
        />
      ) : null}

      {rows.length === 0 && !adding && (
        <Button onClick={() => setAdding(true)}>Add your first account</Button>
      )}

      {GROUP_ORDER.map((key) => {
        const inGroup = rows.filter(
          // A settled IOU is finished: it contributes nothing to the total, so hiding
          // it costs no accuracy and keeps the list to live relationships.
          (a) => groupOf(a) === key && !(a.type === 'person' && a.balance_cents === 0),
        );
        if (!inGroup.length) return null;
        return (
          <div key={key} className="flex flex-col gap-2.5">
            <SectionLabel>{GROUP_LABELS[key]}</SectionLabel>
            <Card className="flex flex-col gap-4">
              {inGroup.map((account, i) => (
                <AccountRow key={account.id} account={account} last={i === inGroup.length - 1} />
              ))}
            </Card>
          </div>
        );
      })}
    </section>
  );
}

function AccountRow({ account, last }: { account: Account; last: boolean }) {
  const update = useUpdateAccount();
  const remove = useDeleteAccount();
  const [open, setOpen] = useState(false);
  const [reconciling, setReconciling] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center justify-between gap-4 text-left"
      >
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink">{account.name}</div>
          <div className="mt-0.5 text-[13px] text-muted">
            {account.entry_count === 0
              ? 'No entries yet'
              : `${account.entry_count} ${account.entry_count === 1 ? 'entry' : 'entries'}`}
          </div>
        </div>
        <span className="num shrink-0 text-[16px] font-semibold">
          <Money
            cents={account.balance_cents}
            tone={account.balance_cents < 0 ? 'over' : 'default'}
          />
        </span>
      </button>

      {open && (
        <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-muted">
          <span>
            Opened {account.opened_on} at {formatMoney(account.opening_balance_cents)}
          </span>
          <span className="grow" />
          <Button variant="ghost" onClick={() => setReconciling((v) => !v)}>
            Reconcile
          </Button>
          {account.entry_count === 0 ? (
            <Button
              variant="ghost"
              onClick={() => remove.mutate(account.id)}
              disabled={remove.isPending}
            >
              Delete
            </Button>
          ) : (
            <Button
              variant="ghost"
              onClick={() => update.mutate({ id: account.id, archived: true })}
              disabled={update.isPending}
            >
              Archive
            </Button>
          )}
        </div>
      )}
      {open && reconciling && <Reconcile account={account} onDone={() => setReconciling(false)} />}
      {!last && <div className="h-px bg-line" />}
    </div>
  );
}

function Reconcile({ account, onDone }: { account: Account; onDone: () => void }) {
  const reconcile = useReconcileAccount();
  const [value, setValue] = useState(String(account.balance_cents / 100));

  const actual = parseAmountToCents(value.replace('-', ''));
  const signed = actual == null ? null : value.trim().startsWith('-') ? -actual : actual;
  const delta = signed == null ? null : signed - account.balance_cents;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (signed == null) return;
    reconcile.mutate({ id: account.id, actualBalanceCents: signed }, { onSuccess: onDone });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2.5 rounded-input bg-inset p-3">
      <Field label="What does the bank actually say?">
        <TextInput
          autoFocus
          inputMode="decimal"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </Field>
      {/* Says what will be written before it is written. The correction shows up in
          the activity list afterwards — a balance that changes with nothing to explain
          it is the thing this app must never do. */}
      <p className="text-[13px] text-muted">
        {delta == null || delta === 0
          ? 'No correction needed — that matches.'
          : `Frankly will log a correction of ${formatMoney(delta, { signed: true })}.`}
      </p>
      <div className="flex items-center gap-2.5">
        <Button type="submit" disabled={signed == null || reconcile.isPending}>
          {reconcile.isPending ? 'Saving…' : 'Correct it'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {reconcile.isError && <p className="text-[13px] text-over">Couldn't save — try again.</p>}
    </form>
  );
}

function AddAccount({ onDone }: { onDone: () => void }) {
  const create = useCreateAccount();
  const [name, setName] = useState('');
  const [type, setType] = useState<AccountType>('current');
  const [opening, setOpening] = useState('');
  const [openedOn, setOpenedOn] = useState(todayISO());

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      {
        name: name.trim(),
        type,
        // Signed on purpose: an overdraft or a card legitimately opens negative.
        opening_balance_cents: parseAmountToCents(opening.replace('-', '')) ?? 0,
        opened_on: openedOn,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Name">
          <TextInput
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Everyday"
          />
        </Field>

        <Field label="Type">
          <div className="flex flex-wrap gap-2">
            {TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setType(t.value)}
                aria-pressed={type === t.value}
                title={t.hint}
                className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium ${
                  type === t.value
                    ? 'bg-ink text-paper'
                    : 'border border-line-2 bg-surface text-ink-2'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Balance today">
          <TextInput
            inputMode="decimal"
            value={opening}
            onChange={(e) => setOpening(e.target.value)}
            placeholder="0"
          />
        </Field>

        <Field label="As of">
          <TextInput type="date" value={openedOn} onChange={(e) => setOpenedOn(e.target.value)} />
        </Field>

        {/* The honesty note: this is where the balance starts counting from, and
            anything logged before it stays out of it. */}
        <p className="text-[13px] text-muted">
          Frankly counts entries from this date on. Anything logged earlier still counts as
          spending, but not toward this balance.
        </p>

        <div className="flex items-center gap-2.5">
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            {create.isPending ? 'Adding…' : 'Add account'}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
        {create.isError && (
          <p className="text-[13px] text-over">
            Couldn't add that — you may already have an account with this name.
          </p>
        )}
      </form>
    </Card>
  );
}
