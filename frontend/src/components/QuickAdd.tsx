import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  useAccounts,
  useCategories,
  useCreateTransaction,
  useDeleteTransaction,
  useTransactions,
} from '../api/hooks';
import type { Kind, TransactionKind } from '../api/types';
import type { CapturePrefill } from '../capture/CaptureContext';
import { useAuth } from '../auth/useAuth';
import { lastAccount, rememberAccount } from '../lib/lastAccount';
import { categoryColor, categoryTint } from '../lib/categoryColor';
import { rankCategories } from '../lib/categories';
import { currentMonth, shiftDays, todayISO } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';
import { useModal } from '../lib/useModal';
import { Portal } from './ui';

/** Digits + separator + backspace, laid out as a phone keypad. */
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', ',', '0', '⌫'] as const;

const TOP_CATEGORIES = 6;

const KINDS = ['expense', 'income', 'refund', 'transfer'] as const;

/** True on touch-first devices, where we drive the amount with our own keypad so
 *  the OS keyboard doesn't cover the sheet. */
function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches,
  );
  useEffect(() => {
    const mq = window.matchMedia('(pointer: coarse)');
    const on = () => setCoarse(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return coarse;
}

interface Logged {
  id: string;
  amountCents: number;
  kind: TransactionKind;
  categoryName: string | null;
}

/**
 * The capture surface — amount first, one tap to categorise, done.
 *
 * Reachable from anywhere (FAB, `A`, ⌘K) because logging is the thing people come
 * back to do; burying it under the dashboard was what made it feel like a chore.
 * Everything here writes to POST /transactions, so it works with or without the AI.
 */
export function QuickAdd({
  open,
  prefill,
  onClose,
}: {
  open: boolean;
  prefill?: CapturePrefill;
  onClose: () => void;
}) {
  // Mounted only while open, so every visit starts on a blank form by construction
  // rather than by resetting state after the fact.
  if (!open) return null;
  return <QuickAddSheet prefill={prefill} onClose={onClose} />;
}

function QuickAddSheet({ prefill, onClose }: { prefill?: CapturePrefill; onClose: () => void }) {
  const { user } = useAuth();
  const categories = useCategories();
  const accounts = useAccounts();
  const transactions = useTransactions({ month: currentMonth() });
  const create = useCreateTransaction();
  const remove = useDeleteTransaction();
  const coarse = useCoarsePointer();

  const [amount, setAmount] = useState(
    prefill?.amountCents != null ? String(prefill.amountCents / 100).replace('.', ',') : '',
  );
  const [kind, setKind] = useState<TransactionKind>(prefill?.kind ?? 'expense');
  const [categoryId, setCategoryId] = useState<string | null>(prefill?.categoryId ?? null);
  // Only what the user actually tapped. The account in force is derived below, so
  // there is no effect racing the accounts query to seed it.
  const [pickedAccount, setPickedAccount] = useState<string | null>(prefill?.accountId ?? null);
  const [pickedCounter, setPickedCounter] = useState<string | null>(null);
  const [description, setDescription] = useState(prefill?.description ?? '');
  const [occurredOn, setOccurredOn] = useState(todayISO);
  const [showAllCategories, setShowAllCategories] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logged, setLogged] = useState<Logged | null>(null);

  const amountRef = useRef<HTMLInputElement>(null);
  const closeTimer = useRef<number | undefined>(undefined);
  const overlayRef = useModal(onClose);

  // A transfer has no categories at all, so ranking falls back to the expense list
  // rather than being asked to rank against a kind no category can have.
  // A refund undoes an expense, so it picks from the expense categories.
  const categoryKind: Kind = kind === 'income' ? 'income' : 'expense';
  const ranked = useMemo(
    () => rankCategories(categories.data ?? [], transactions.data ?? [], categoryKind),
    [categories.data, transactions.data, categoryKind],
  );
  const visible = showAllCategories ? ranked : ranked.slice(0, TOP_CATEGORIES);
  const cents = parseAmountToCents(amount);

  function reset() {
    setAmount('');
    setDescription('');
    setCategoryId(null);
    setOccurredOn(todayISO());
    setError(null);
    setLogged(null);
    setShowAllCategories(false);
  }

  // Straight into the amount on a real keyboard; on touch the keypad does the work.
  useEffect(() => {
    if (!coarse) {
      const t = window.setTimeout(() => amountRef.current?.focus(), 60);
      return () => window.clearTimeout(t);
    }
  }, [coarse]);

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  const openAccounts = useMemo(
    () => (accounts.data?.accounts ?? []).filter((a) => a.archived_at === null),
    [accounts.data],
  );

  // Money leaves an account on an expense and lands in one on income. Saying "from"
  // both ways would be wrong, and it is what lets a transfer read as "from X to Y".
  // Money leaves an account on an expense, and lands in one on income or a refund.
  const preposition = kind === 'income' || kind === 'refund' ? 'to' : 'from';

  // Derived rather than seeded in an effect: the accounts arrive after first paint,
  // and an effect that writes state would render one frame with nothing selected.
  // null here means the user has no accounts at all, which stays a valid way to log.
  const accountId = useMemo(() => {
    if (pickedAccount && openAccounts.some((a) => a.id === pickedAccount)) return pickedAccount;
    if (!openAccounts.length) return null;
    const remembered = user ? lastAccount(user.id) : null;
    return (openAccounts.find((a) => a.id === remembered) ?? openAccounts[0]).id;
  }, [pickedAccount, openAccounts, user]);

  // A transfer needs somewhere to go that isn't where it came from, so it is only
  // offered once two accounts exist — and the destination can never be the source.
  const canTransfer = openAccounts.length > 1;
  const destinations = useMemo(
    () => openAccounts.filter((a) => a.id !== accountId),
    [openAccounts, accountId],
  );
  const counterAccountId = useMemo(() => {
    if (kind !== 'transfer') return null;
    if (pickedCounter && destinations.some((a) => a.id === pickedCounter)) return pickedCounter;
    return destinations[0]?.id ?? null;
  }, [kind, pickedCounter, destinations]);

  function tapKey(key: string) {
    setError(null);
    if (key === '⌫') return setAmount((a) => a.slice(0, -1));
    if (key === ',') return setAmount((a) => (a.includes(',') ? a : (a || '0') + ','));
    // Two decimals max, and no leading zero pile-up.
    setAmount((a) => {
      const [, frac] = a.split(',');
      if (frac !== undefined && frac.length >= 2) return a;
      return a === '0' ? key : a + key;
    });
  }

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (cents === null) {
      setError('Enter an amount.');
      return;
    }
    const category = ranked.find((c) => c.id === categoryId) ?? null;
    create.mutate(
      {
        amount_cents: cents,
        // Description is optional here on purpose — chasing people for a label is
        // exactly the friction that stops them logging. Fall back to the category.
        description:
          description.trim() ||
          (kind === 'transfer' ? 'Moved between accounts' : null) ||
          category?.name ||
          (kind === 'income' ? 'Income' : kind === 'refund' ? 'Refund' : 'Expense'),
        kind,
        occurred_on: occurredOn,
        category_id: kind === 'transfer' ? null : categoryId,
        account_id: accountId,
        counter_account_id: counterAccountId,
      },
      {
        onSuccess: (tx) => {
          if (user && accountId) rememberAccount(user.id, accountId);
          setLogged({
            id: tx.id,
            amountCents: cents,
            kind,
            categoryName: category?.name ?? null,
          });
          closeTimer.current = window.setTimeout(onClose, 2600);
        },
        onError: () => setError("Couldn't save — try again."),
      },
    );
  }

  function undo() {
    window.clearTimeout(closeTimer.current);
    if (logged) remove.mutate(logged.id);
    onClose();
  }

  function another() {
    window.clearTimeout(closeTimer.current);
    reset();
    if (!coarse) window.setTimeout(() => amountRef.current?.focus(), 60);
  }

  return (
    <Portal>
      <div
        ref={overlayRef}
        className="fixed inset-0 z-50 flex items-end justify-center focus:outline-none sm:items-center sm:p-4"
        role="dialog"
        aria-modal="true"
        aria-label={kind === 'income' ? 'Log income' : 'Log an expense'}
      >
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="animate-fade-in absolute inset-0 cursor-default bg-black/45 backdrop-blur-[2px]"
        />

        <div
          className="animate-sheet-in relative flex max-h-[92svh] w-full flex-col overflow-y-auto rounded-t-[22px] border border-line-2 bg-surface sm:max-h-[calc(100svh-2rem)] sm:max-w-[440px] sm:rounded-card"
          style={{ boxShadow: '0 24px 70px rgba(0,0,0,0.42)' }}
        >
          {logged ? (
            <LoggedFlash logged={logged} onUndo={undo} onAnother={another} onDone={onClose} />
          ) : (
            <form onSubmit={submit} className="flex flex-col">
              {/* Header: what kind of thing is this, and a way out */}
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <div className="flex rounded-full bg-inset p-1">
                  {KINDS.filter((k) => k !== 'transfer' || canTransfer).map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => {
                        setKind(k);
                        setCategoryId(null);
                      }}
                      className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold capitalize transition-colors ${
                        kind === k ? 'bg-surface text-ink' : 'text-muted hover:text-ink-2'
                      }`}
                      style={kind === k ? { boxShadow: 'var(--shadow)' } : undefined}
                    >
                      {k}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close"
                  className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-inset hover:text-ink"
                >
                  <svg
                    width="17"
                    height="17"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                  >
                    <path d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Amount — the first and often only thing they need to touch */}
              <div className="flex items-center justify-center gap-1.5 px-4 pt-7 pb-5">
                <span
                  className="num text-[30px] font-medium"
                  style={{ color: amount ? 'var(--muted)' : 'var(--faint)' }}
                >
                  {kind === 'income' ? '+' : '−'}
                </span>
                <input
                  ref={amountRef}
                  value={amount}
                  onChange={(e) => {
                    setError(null);
                    setAmount(e.target.value.replace(/[^\d.,]/g, ''));
                  }}
                  readOnly={coarse}
                  inputMode={coarse ? 'none' : 'decimal'}
                  placeholder="0,00"
                  aria-label="Amount"
                  className="num w-full max-w-[240px] bg-transparent text-center text-[52px] font-semibold tracking-[-0.03em] text-ink placeholder:text-faint focus:outline-none"
                />
                <span className="num text-[30px] font-medium text-muted">€</span>
              </div>

              {/* Where the money moved, read as part of the amount rather than as a
                  second row of pills.

                  Account and category are not the same kind of choice. The category
                  changes almost every time; the account almost never does, and the last
                  one is remembered anyway. Giving them matching chip rows implied they
                  were equal weight, and left two unlabelled rows of pills separated only
                  by the category dots — legible with three accounts, not with eight.
                  Sitting under the figure it reads as a sentence ("23,50 € from
                  Everyday"), takes one line instead of a wrapping row, and scales to any
                  number of accounts because the list is inside the control.

                  The preposition follows the direction, which is also the honest word:
                  money leaves an account on an expense and lands in one on income. */}
              {openAccounts.length > 0 && (
                <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-2 px-4 pb-4">
                  {openAccounts.length === 1 ? (
                    <span className="text-[13px] text-muted">
                      {preposition} <span className="text-ink-2">{openAccounts[0].name}</span>
                    </span>
                  ) : (
                    <label className="flex items-center gap-2 text-[13px] text-muted">
                      {preposition}
                      <select
                        value={accountId ?? ''}
                        onChange={(e) => setPickedAccount(e.target.value)}
                        aria-label="Account"
                        className="h-9 rounded-input border border-line-2 bg-field px-2.5 text-[13px] text-ink-2 focus:outline-none"
                      >
                        {openAccounts.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}

                  {/* The far half of the sentence. Only a transfer has one, and the
                      source is never in the list — a transfer to itself is refused by
                      the database, so it should not be offerable here either. */}
                  {kind === 'transfer' && (
                    <label className="flex items-center gap-2 text-[13px] text-muted">
                      to
                      <select
                        value={counterAccountId ?? ''}
                        onChange={(e) => setPickedCounter(e.target.value)}
                        aria-label="Destination account"
                        className="h-9 rounded-input border border-line-2 bg-field px-2.5 text-[13px] text-ink-2 focus:outline-none"
                      >
                        {destinations.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
              )}

              {/* Categories — one tap, most-used first. Absent for a transfer: a
                  category is how spend reaches a budget, and moving your own money
                  between accounts is not spend. The DB constraint agrees. */}
              {kind !== 'transfer' && (
                <div className="flex flex-wrap gap-2 px-4 pb-4">
                  {visible.map((c) => {
                    const on = categoryId === c.id;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => setCategoryId(on ? null : c.id)}
                        className={`flex items-center gap-2 rounded-full border px-3 py-2 text-[13.5px] font-medium transition-colors ${
                          on ? 'text-ink' : 'border-line-2 text-ink-2 hover:text-ink'
                        }`}
                        style={
                          on
                            ? {
                                borderColor: categoryColor(c.name),
                                background: categoryTint(c.name),
                              }
                            : undefined
                        }
                      >
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: categoryColor(c.name) }}
                        />
                        {c.name}
                      </button>
                    );
                  })}
                  {!showAllCategories && ranked.length > TOP_CATEGORIES && (
                    <button
                      type="button"
                      onClick={() => setShowAllCategories(true)}
                      className="rounded-full border border-dashed border-line-2 px-3 py-2 text-[13.5px] font-medium text-muted hover:text-ink"
                    >
                      more…
                    </button>
                  )}
                </div>
              )}

              {/* Optional detail */}
              <div className="flex flex-col gap-2.5 px-4 pb-4">
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={500}
                  placeholder="What was it? (optional)"
                  aria-label="Description"
                  className="h-11 rounded-input border border-line-2 bg-field px-3 text-[15px] text-ink placeholder:text-faint focus:outline-none"
                />
                <div className="flex items-center gap-2">
                  {(
                    [
                      ['Today', todayISO()],
                      ['Yesterday', shiftDays(todayISO(), -1)],
                    ] as const
                  ).map(([label, iso]) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => setOccurredOn(iso)}
                      className={`rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors ${
                        occurredOn === iso
                          ? 'border-ink-2 text-ink'
                          : 'border-line-2 text-muted hover:text-ink-2'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                  <input
                    type="date"
                    value={occurredOn}
                    onChange={(e) => setOccurredOn(e.target.value)}
                    aria-label="Date"
                    className="ml-auto h-9 rounded-input border border-line-2 bg-field px-2.5 text-[13px] text-ink-2 focus:outline-none"
                  />
                </div>
              </div>

              {/* Keypad, on touch only */}
              {coarse && (
                <div className="grid grid-cols-3 gap-1.5 px-4 pb-3">
                  {KEYS.map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => tapKey(k)}
                      className="num h-14 rounded-[14px] bg-inset text-[22px] font-medium text-ink active:opacity-60"
                    >
                      {k}
                    </button>
                  ))}
                </div>
              )}

              {error && <p className="px-4 pb-2 text-[13px] text-over">{error}</p>}

              <div className="sticky bottom-0 border-t border-line bg-surface px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
                <button
                  type="submit"
                  disabled={cents === null || create.isPending}
                  className="h-12 w-full rounded-input bg-ink text-[15px] font-semibold text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {create.isPending
                    ? 'Saving…'
                    : cents === null
                      ? 'Enter an amount'
                      : `Log ${formatMoney(cents)}`}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </Portal>
  );
}

/** The beat after saving: confirm what landed, and make undo the easy option. */
function LoggedFlash({
  logged,
  onUndo,
  onAnother,
  onDone,
}: {
  logged: Logged;
  onUndo: () => void;
  onAnother: () => void;
  onDone: () => void;
}) {
  const income = logged.kind === 'income';
  return (
    <div className="flex flex-col items-center gap-1 px-6 py-9 text-center">
      <span
        className="animate-tick mb-2 grid h-14 w-14 place-items-center rounded-full"
        style={{ background: 'var(--go-soft)', color: 'var(--go)' }}
      >
        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      </span>
      <p className="num text-[28px] font-semibold tracking-[-0.02em] text-ink">
        {formatMoney(logged.amountCents, { signed: income })}
      </p>
      <p className="text-[14px] text-muted">
        {logged.kind === 'transfer' ? 'Moved' : income ? 'Income logged' : 'Logged'}
        {logged.categoryName ? ` · ${logged.categoryName}` : ''}
      </p>
      <div className="mt-5 flex w-full items-center gap-2">
        <button
          type="button"
          onClick={onUndo}
          className="h-11 flex-1 rounded-input border border-line-2 text-[14px] font-semibold text-ink-2 hover:text-ink"
        >
          Undo
        </button>
        <button
          type="button"
          onClick={onAnother}
          className="h-11 flex-1 rounded-input bg-ink text-[14px] font-semibold text-paper hover:opacity-90"
        >
          Log another
        </button>
      </div>
      <button
        type="button"
        onClick={onDone}
        className="mt-3 text-[13px] font-medium text-faint hover:text-ink-2"
      >
        Done
      </button>
    </div>
  );
}
