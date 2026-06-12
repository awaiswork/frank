import { useState, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import { useCategories, useCreateTransaction, useParseNl } from '../api/hooks';
import type { Category, Kind, NlDraft } from '../api/types';
import { parseAmountToCents } from '../lib/money';
import { Button, Card } from './ui';

type DraftItem = NlDraft & { _id: string };

/**
 * Natural-language capture (technical-plan.md §7b, design "Capture"). The user
 * types it like they'd say it; Frank parses into drafts they confirm or correct
 * before anything saves. Shared between Home and Transactions.
 */
export function Capture() {
  const parse = useParseNl();
  const categories = useCategories();
  const [text, setText] = useState('');
  const [drafts, setDrafts] = useState<DraftItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    setError(null);
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
    <Card>
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <input
          className="h-12 w-full bg-transparent text-[16px] text-ink placeholder:text-faint focus:outline-none"
          placeholder="Tell Frank what you spent — “8,40 coffee and croissant”"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={500}
          aria-label="Natural-language capture"
        />
        <Button type="submit" disabled={parse.isPending || !text.trim()}>
          {parse.isPending ? 'Reading…' : 'Capture'}
        </Button>
      </form>

      {parse.isPending && (
        <p className="mt-3 animate-pulse text-[13px] text-muted">Frank is reading your note…</p>
      )}
      {error && <p className="mt-3 text-[13px] text-over">{error}</p>}

      {drafts.length > 0 && (
        <div className="mt-4 flex flex-col gap-3">
          <p className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">
            {drafts.length === 1 ? 'Confirm this draft' : `Confirm these ${drafts.length} drafts`}
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
    </Card>
  );
}

function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace('.', ',');
}

function confidence(c: number): { label: string; cls: string } {
  if (c >= 0.85) return { label: 'sure', cls: 'text-go' };
  if (c >= 0.6) return { label: 'fairly sure', cls: 'text-wait' };
  return { label: 'a guess', cls: 'text-over' };
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
  const fieldClass = 'h-10 rounded-input border border-line-2 bg-field px-3 text-[15px] text-ink';

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
    <div className="animate-fade-up rounded-input border border-line bg-surface-2 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[12px] text-muted">
          Frank is <span className={`font-semibold ${conf.cls}`}>{conf.label}</span>
          {draft.merchant ? ` · ${draft.merchant}` : ''}
        </span>
        <button type="button" onClick={onDone} className="text-[13px] text-faint hover:text-ink-2">
          Discard
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <input
          className={`${fieldClass} ${err ? 'border-over' : ''}`}
          inputMode="decimal"
          aria-label="Amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <input
          type="date"
          className={fieldClass}
          aria-label="Date"
          value={occurredOn}
          onChange={(e) => setOccurredOn(e.target.value)}
        />
        <select
          className={fieldClass}
          aria-label="Type"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
        >
          <option value="expense">Expense</option>
          <option value="income">Income</option>
        </select>
        <select
          className={fieldClass}
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
      </div>

      <div className="mt-3 flex items-center gap-2">
        <input
          className={`${fieldClass} flex-1`}
          aria-label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Button type="button" disabled={create.isPending} onClick={log}>
          {create.isPending ? 'Saving…' : 'Log it'}
        </Button>
      </div>
    </div>
  );
}
