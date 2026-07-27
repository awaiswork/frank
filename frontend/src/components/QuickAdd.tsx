import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  useCategories,
  useCreateTransaction,
  useDeleteTransaction,
  useTransactions,
} from '../api/hooks';
import type { Kind } from '../api/types';
import { categoryColor, categoryTint } from '../lib/categoryColor';
import { rankCategories } from '../lib/categories';
import { currentMonth, shiftDays, todayISO } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';

/** Digits + separator + backspace, laid out as a phone keypad. */
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', ',', '0', '⌫'] as const;

const TOP_CATEGORIES = 6;

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
  kind: Kind;
  categoryName: string | null;
}

/**
 * The capture surface — amount first, one tap to categorise, done.
 *
 * Reachable from anywhere (FAB, `A`, ⌘K) because logging is the thing people come
 * back to do; burying it under the dashboard was what made it feel like a chore.
 * Everything here writes to POST /transactions, so it works with or without the AI.
 */
export function QuickAdd({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Mounted only while open, so every visit starts on a blank form by construction
  // rather than by resetting state after the fact.
  if (!open) return null;
  return <QuickAddSheet onClose={onClose} />;
}

function QuickAddSheet({ onClose }: { onClose: () => void }) {
  const categories = useCategories();
  const transactions = useTransactions({ month: currentMonth() });
  const create = useCreateTransaction();
  const remove = useDeleteTransaction();
  const coarse = useCoarsePointer();

  const [amount, setAmount] = useState('');
  const [kind, setKind] = useState<Kind>('expense');
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [occurredOn, setOccurredOn] = useState(todayISO);
  const [showAllCategories, setShowAllCategories] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logged, setLogged] = useState<Logged | null>(null);

  const amountRef = useRef<HTMLInputElement>(null);
  const closeTimer = useRef<number | undefined>(undefined);

  const ranked = useMemo(
    () => rankCategories(categories.data ?? [], transactions.data ?? [], kind),
    [categories.data, transactions.data, kind],
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

  // Esc closes from anywhere inside the sheet.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Don't let the page behind scroll under the sheet.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

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
          description.trim() || category?.name || (kind === 'income' ? 'Income' : 'Expense'),
        kind,
        occurred_on: occurredOn,
        category_id: categoryId,
      },
      {
        onSuccess: (tx) => {
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
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
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
        className="animate-sheet-in relative flex max-h-[92svh] w-full flex-col overflow-y-auto rounded-t-[22px] border border-line-2 bg-surface sm:max-w-[440px] sm:rounded-card"
        style={{ boxShadow: '0 24px 70px rgba(0,0,0,0.42)' }}
      >
        {logged ? (
          <LoggedFlash logged={logged} onUndo={undo} onAnother={another} onDone={onClose} />
        ) : (
          <form onSubmit={submit} className="flex flex-col">
            {/* Header: what kind of thing is this, and a way out */}
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex rounded-full bg-inset p-1">
                {(['expense', 'income'] as const).map((k) => (
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

            {/* Categories — one tap, most-used first */}
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
        {income ? 'Income logged' : 'Logged'}
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
