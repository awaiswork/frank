import { useRef, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { askAdvisor, previewFromPartial } from '../api/advisor';
import { useAdviceHistory, useSetFollowed } from '../api/hooks';
import type { AdviceHistory, AdviceVerdict } from '../api/types';
import { VerdictStamp } from '../components/VerdictStamp';
import { Button, Card, EmptyState, SectionLabel, TextInput } from '../components/ui';
import { parseAmountToCents } from '../lib/money';
import { verdictLabel, verdictSoft } from '../lib/verdict';

export function Advisor() {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');
  const [amount, setAmount] = useState('');
  const [partial, setPartial] = useState('');
  const [verdict, setVerdict] = useState<AdviceVerdict | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || streaming) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setVerdict(null);
    setPartial('');
    setStreaming(true);

    const amountCents = amount.trim() ? parseAmountToCents(amount) : null;
    void askAdvisor(
      { question: question.trim(), amount_cents: amountCents },
      {
        onDelta: setPartial,
        onVerdict: setVerdict,
        onError: (message) => {
          setError(message);
          setStreaming(false);
        },
        onDone: () => {
          setStreaming(false);
          void queryClient.invalidateQueries({ queryKey: ['advice'] });
        },
      },
      controller.signal,
    ).catch(() => {
      setError('Something went wrong reaching Frank.');
      setStreaming(false);
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-[22px] font-bold text-ink">Ask Frank</h1>

      <Card>
        <form onSubmit={onAsk} className="flex flex-col gap-3">
          <TextInput
            placeholder="Should I buy 240€ headphones?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={300}
            aria-label="Your question"
          />
          <div className="flex items-center gap-2">
            <TextInput
              className="max-w-40"
              inputMode="decimal"
              placeholder="Amount (optional)"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-label="Amount"
            />
            <div className="flex-1" />
            <Button type="submit" disabled={streaming || !question.trim()}>
              {streaming ? 'Thinking…' : 'Ask Frank'}
            </Button>
          </div>
        </form>
      </Card>

      {error && <Card className="text-[14px] text-over">{error}</Card>}
      {verdict && <FinalVerdict verdict={verdict} />}
      {!verdict && streaming && <StreamingPreview partial={partial} />}

      <History />
    </div>
  );
}

function FinalVerdict({ verdict }: { verdict: AdviceVerdict }) {
  return (
    <Card className="overflow-hidden p-0">
      <div
        className="flex items-center gap-5 px-5 py-5"
        style={{ background: verdictSoft(verdict.verdict) }}
      >
        <VerdictStamp verdict={verdict.verdict} size={84} animate />
        <div className="min-w-0">
          <p className="text-[11px] tracking-[0.1em] text-muted uppercase">Frank says</p>
          <p className="font-display text-[24px] leading-tight font-bold text-ink">
            {verdict.headline}
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-4 p-5">
        {verdict.evidence.length > 0 && (
          <div className="flex flex-col">
            {verdict.evidence.map((e, i) => (
              <div
                key={i}
                className="flex items-baseline justify-between border-b border-line py-2 text-[14px] last:border-0"
              >
                <span className="text-muted">{e.label}</span>
                <span className="num font-medium text-ink">{e.value}</span>
              </div>
            ))}
          </div>
        )}
        <p className="text-[14.5px] leading-relaxed text-ink-2">{verdict.reasoning}</p>
        <p className="text-[12px] text-faint">{verdict.disclaimer}</p>
      </div>
    </Card>
  );
}

function StreamingPreview({ partial }: { partial: string }) {
  const preview = previewFromPartial(partial);
  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-center gap-5">
        {preview.verdict ? (
          <VerdictStamp verdict={preview.verdict} size={72} animate />
        ) : (
          <div className="h-[72px] w-[72px] animate-pulse rounded-full border-2 border-dashed border-line-2" />
        )}
        <div>
          <p className="animate-pulse text-[11px] tracking-[0.1em] text-muted uppercase">
            Frank is weighing it up…
          </p>
          {preview.headline && (
            <p className="font-display text-[20px] font-bold text-ink">{preview.headline}</p>
          )}
        </div>
      </div>
      {preview.reasoning && (
        <p className="text-[14.5px] leading-relaxed text-ink-2">
          {preview.reasoning}
          <span className="animate-pulse">▋</span>
        </p>
      )}
    </Card>
  );
}

function History() {
  const history = useAdviceHistory();
  if (!history.data || history.data.length === 0) {
    return (
      <section className="flex flex-col gap-3">
        <SectionLabel>Past questions</SectionLabel>
        <EmptyState title="No questions yet" hint="Ask Frank about a purchase you're weighing." />
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3">
      <SectionLabel>Past questions</SectionLabel>
      {history.data.map((item) => (
        <HistoryRow key={item.id} item={item} />
      ))}
    </section>
  );
}

function HistoryRow({ item }: { item: AdviceHistory }) {
  const setFollowed = useSetFollowed();
  return (
    <Card className="flex items-center gap-4">
      {item.verdict && <VerdictStamp verdict={item.verdict} size={42} label={false} />}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14.5px] font-medium text-ink">{item.question}</p>
        <p className="text-[12px] text-muted">
          {item.verdict ? verdictLabel(item.verdict) : 'No verdict'} ·{' '}
          {new Date(item.created_at).toLocaleDateString()}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2 text-[12px]">
        {item.user_followed === null ? (
          <>
            <span className="text-muted">Did you?</span>
            <button
              type="button"
              className="rounded-full border border-line-2 px-3 py-1 text-ink-2 hover:text-ink"
              onClick={() => setFollowed.mutate({ id: item.id, followed: true })}
            >
              Yes
            </button>
            <button
              type="button"
              className="rounded-full border border-line-2 px-3 py-1 text-ink-2 hover:text-ink"
              onClick={() => setFollowed.mutate({ id: item.id, followed: false })}
            >
              No
            </button>
          </>
        ) : (
          <span className="text-ink-2">
            {item.user_followed ? 'You went ahead' : 'You held off'}
          </span>
        )}
      </div>
    </Card>
  );
}
