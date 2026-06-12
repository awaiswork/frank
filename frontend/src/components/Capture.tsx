import { useEffect, useState, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import { useCategories, useCreateTransaction, useParseNl } from '../api/hooks';
import type { Category, Kind, NlDraft } from '../api/types';
import { categoryColor } from '../lib/categoryColor';
import { parseAmountToCents } from '../lib/money';
import { Button } from './ui';

type DraftItem = NlDraft & { _id: string };

const TICKS = [
  'Reading the amount',
  'Picking a category',
  'Spotting the merchant',
  'Setting the date',
];

/**
 * Natural-language capture (technical-plan.md §7b, design "Capture"). Type it
 * like you'd say it; Frank parses into drafts you confirm before anything saves.
 */
export function Capture({ placeholder }: { placeholder?: string }) {
  const parse = useParseNl();
  const categories = useCategories();
  const [text, setText] = useState('');
  const [drafts, setDrafts] = useState<DraftItem[]>([]);
  const [reading, setReading] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // March the parsing ticks while the request is in flight (the "reading" moment).
  useEffect(() => {
    if (!parse.isPending) return;
    const ts = [420, 760, 1080, 1360].map((ms, i) => setTimeout(() => setTick(i + 1), ms));
    return () => ts.forEach(clearTimeout);
  }, [parse.isPending]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || parse.isPending) return;
    setError(null);
    setTick(0);
    setReading(value);
    parse.mutate(value, {
      onSuccess: (result) => {
        setDrafts(result.map((d) => ({ ...d, _id: crypto.randomUUID() })));
        setText('');
      },
      onError: (err) =>
        setError(err instanceof ApiError ? err.message : 'Frank could not read that.'),
    });
  }

  function removeDraft(id: string) {
    setDrafts((cur) => cur.filter((d) => d._id !== id));
  }

  return (
    <div className="flex flex-col">
      <form
        onSubmit={onSubmit}
        className="flex items-center gap-2.5 rounded-card border border-line-2 bg-surface py-2 pr-2 pl-[18px]"
        style={{ boxShadow: 'var(--shadow)' }}
      >
        <span className="grid place-items-center text-muted">
          <svg
            width="19"
            height="19"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </span>
        <input
          className="min-w-0 flex-1 bg-transparent py-2 text-[16px] text-ink placeholder:text-faint focus:outline-none"
          placeholder={placeholder ?? 'Tell Frank what you spent — “8,40 coffee and croissant”'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={500}
          aria-label="Natural-language capture"
        />
        <Button type="submit" disabled={parse.isPending || !text.trim()}>
          {parse.isPending ? 'Reading…' : 'Log it'}
        </Button>
      </form>

      {parse.isPending && (
        <div
          className="animate-pop mt-[18px] rounded-card border border-line bg-surface p-[22px]"
          style={{ boxShadow: 'var(--shadow)' }}
        >
          <div className="mb-4 flex items-center gap-2.5 text-[14.5px] font-semibold">
            <span className="animate-spin-fast inline-block h-4 w-4 rounded-full border-2 border-line-2 border-t-ink" />
            Frank is reading “{reading}”
          </div>
          <div className="flex flex-col gap-2.5">
            {TICKS.map((label, i) => {
              const done = tick > i;
              return (
                <div
                  key={label}
                  className="flex items-center gap-2.5 text-[14px]"
                  style={{ color: done ? 'var(--ink)' : 'var(--muted)' }}
                >
                  <span
                    className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border-[1.5px]"
                    style={{ borderColor: done ? 'var(--go)' : 'var(--line-2)' }}
                  >
                    {done && (
                      <span className="animate-tick text-go">
                        <svg
                          width="11"
                          height="11"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="3.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M20 6 9 17l-5-5" />
                        </svg>
                      </span>
                    )}
                  </span>
                  {label}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-[13px] text-over">{error}</p>}

      {drafts.length > 0 && (
        <div className="mt-[18px] flex flex-col gap-3.5">
          <p className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">
            {drafts.length === 1 ? 'Confirm to save' : `Confirm these ${drafts.length}`}
          </p>
          {drafts.map((d) => (
            <DraftCard
              key={d._id}
              draft={d}
              categories={categories.data ?? []}
              onDone={() => removeDraft(d._id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace('.', ',');
}

function confidence(c: number): { label: string; color: string } {
  if (c >= 0.85) return { label: 'sure', color: 'var(--go)' };
  if (c >= 0.6) return { label: 'fairly sure', color: 'var(--wait)' };
  return { label: 'a guess', color: 'var(--over)' };
}

function DraftCard({
  draft,
  categories,
  onDone,
}: {
  draft: NlDraft;
  categories: Category[];
  onDone: () => void;
}) {
  const create = useCreateTransaction();
  const [amount, setAmount] = useState(centsToInput(draft.amount_cents));
  const [description, setDescription] = useState(draft.description);
  const [kind, setKind] = useState<Kind>(draft.kind);
  const [categoryId, setCategoryId] = useState(draft.category_id ?? '');
  const [occurredOn, setOccurredOn] = useState(draft.occurred_on);
  const [err, setErr] = useState(false);

  const conf = confidence(draft.confidence);
  const selected = categories.find((c) => c.id === categoryId) ?? null;
  const field =
    'h-10 rounded-[10px] border border-line-2 bg-field px-3 text-[14.5px] text-ink focus:outline-none';

  function log() {
    const cents = parseAmountToCents(amount);
    if (cents === null || !description.trim()) {
      setErr(true);
      return;
    }
    setErr(false);
    create.mutate(
      {
        amount_cents: cents,
        description: description.trim(),
        kind,
        occurred_on: occurredOn,
        category_id: categoryId || null,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <div
      className="animate-pop overflow-hidden rounded-card border border-line-2 bg-surface"
      style={{ boxShadow: 'var(--shadow)' }}
    >
      <div className="flex items-center justify-between border-b border-line px-[18px] py-3">
        <span className="text-[12px] text-muted">
          Frank is{' '}
          <span className="font-semibold" style={{ color: conf.color }}>
            {conf.label}
          </span>
          {draft.merchant ? ` · ${draft.merchant}` : ''}
        </span>
        <button type="button" onClick={onDone} className="text-[13px] text-faint hover:text-ink-2">
          Discard
        </button>
      </div>

      {/* Amount */}
      <div
        className="animate-field-in border-b border-line p-[18px]"
        style={{ animationDelay: '0.05s' }}
      >
        <div className="mb-1 text-[12px] font-semibold text-muted">Amount</div>
        <div className="flex items-baseline gap-1">
          <input
            inputMode="decimal"
            aria-label="Amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={`num w-32 bg-transparent text-[34px] font-semibold tracking-[-0.02em] focus:outline-none ${
              err ? 'text-over' : 'text-ink'
            }`}
          />
          <span className="num text-[18px] text-muted">€</span>
        </div>
      </div>

      {/* Category + type */}
      <div
        className="animate-field-in grid grid-cols-2 gap-2 border-b border-line p-[18px]"
        style={{ animationDelay: '0.13s' }}
      >
        <label className="flex items-center gap-2">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: selected ? categoryColor(selected.name) : 'var(--muted)' }}
          />
          <select
            className={`${field} flex-1`}
            aria-label="Category"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            <option value="">No category</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <select
          className={field}
          aria-label="Type"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
        >
          <option value="expense">Expense</option>
          <option value="income">Income</option>
        </select>
      </div>

      {/* Description + date */}
      <div
        className="animate-field-in flex flex-col gap-2.5 p-[18px] sm:flex-row sm:items-center"
        style={{ animationDelay: '0.21s' }}
      >
        <input
          className={`${field} flex-1`}
          aria-label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          type="date"
          className={`${field} sm:w-40`}
          aria-label="Date"
          value={occurredOn}
          onChange={(e) => setOccurredOn(e.target.value)}
        />
        <Button type="button" disabled={create.isPending} onClick={log} className="h-10">
          {create.isPending ? 'Saving…' : 'Log it'}
        </Button>
      </div>
    </div>
  );
}
