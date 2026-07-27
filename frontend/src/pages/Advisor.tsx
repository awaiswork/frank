import { useRef, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { askAdvisor, previewFromPartial } from '../api/advisor';
import { useAdviceHistory, useFeatures, useSetFollowed } from '../api/hooks';
import type { AdviceHistory, AdviceVerdict } from '../api/types';
import { VerdictStamp } from '../components/VerdictStamp';
import { ComingSoonBadge } from '../components/bits';
import { Button, Card, EmptyState, SectionLabel } from '../components/ui';
import { verdictLabel, verdictSoft } from '../lib/verdict';

const SUGGESTIONS: ReadonlyArray<readonly [string, string]> = [
  ['Headphones', 'Should I buy 240€ headphones?'],
  ['Weekend trip', 'Should I take a 480€ weekend trip?'],
  ['New laptop', 'Should I buy a 1200€ laptop?'],
  ['Coffee', 'Should I get a 3,50€ coffee?'],
];

export function Advisor() {
  const queryClient = useQueryClient();
  const { features, ready } = useFeatures();
  const off = ready && !features.advisor;
  const [question, setQuestion] = useState('');
  const [partial, setPartial] = useState('');
  const [verdict, setVerdict] = useState<AdviceVerdict | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function runAsk(q: string) {
    // Fail closed — the API 503s this while the feature is off, but never ask.
    if (!q.trim() || streaming || !features.advisor) return;
    setQuestion(q);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setVerdict(null);
    setPartial('');
    setStreaming(true);

    void askAdvisor(
      { question: q.trim() },
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

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    runAsk(question);
  }

  return (
    <section className="animate-fade-up mx-auto flex max-w-[640px] flex-col gap-[18px]">
      <div>
        <div className="flex items-center gap-3">
          <h1 className="font-display text-[24px] font-semibold tracking-[-0.02em]">Ask Frank</h1>
          {off && <ComingSoonBadge />}
        </div>
        <p className="mt-1 text-[14.5px] text-muted">
          Thinking about a purchase? Frank checks your real budgets and goals, then gives you a
          straight answer.
        </p>
      </div>

      <form
        onSubmit={onSubmit}
        className={`flex items-center gap-2.5 rounded-card border bg-surface py-2 pr-2 pl-[18px] ${
          off ? 'border-dashed border-line-2 opacity-70' : 'border-line-2'
        }`}
        style={{ boxShadow: 'var(--shadow)' }}
      >
        <input
          value={off ? '' : question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={300}
          disabled={off}
          readOnly={off}
          placeholder="Should I buy…"
          aria-label={off ? 'Your question (coming soon)' : 'Your question'}
          className={`min-w-0 flex-1 bg-transparent py-2 text-[16px] placeholder:text-faint focus:outline-none ${
            off ? 'cursor-not-allowed text-faint' : 'text-ink'
          }`}
        />
        {off ? (
          <ComingSoonBadge />
        ) : (
          <Button type="submit" disabled={streaming || !question.trim()}>
            {streaming ? 'Thinking…' : 'Ask'}
          </Button>
        )}
      </form>

      {off && <ComingSoonNotice />}

      {!off && !streaming && !verdict && (
        <div className="flex flex-wrap gap-2.5">
          {SUGGESTIONS.map(([label, q]) => (
            <button
              key={label}
              onClick={() => runAsk(q)}
              className="rounded-full border border-line-2 bg-surface px-3.5 py-2 text-[13.5px] font-medium text-ink-2 hover:text-ink"
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {error && <Card className="text-[14px] text-over">{error}</Card>}
      {verdict && <FinalVerdict verdict={verdict} />}
      {!verdict && streaming && <StreamingPreview partial={partial} />}

      <History />
    </section>
  );
}

/** Shown in place of the verdict card while the Advisor is switched off. */
function ComingSoonNotice() {
  // Past verdicts are already stored, so reading them costs nothing — say so,
  // but only when there's actually something down there.
  const history = useAdviceHistory();
  const hasHistory = (history.data?.length ?? 0) > 0;
  return (
    <Card className="flex flex-col gap-3">
      <p className="font-display text-[19px] font-semibold tracking-[-0.01em] text-ink">
        Frank's verdicts are on the way.
      </p>
      <p className="text-[14.5px] leading-relaxed text-ink-2">
        Asking Frank means running your numbers through a model, so it's switched off for now.
        Everything that doesn't cost anything still works — your safe-to-spend, budgets, goals and
        insights are all live on the other tabs.
      </p>
      {hasHistory && (
        <p className="text-[13px] text-faint">
          Anything you asked before is still here, just below.
        </p>
      )}
    </Card>
  );
}

function FinalVerdict({ verdict }: { verdict: AdviceVerdict }) {
  return (
    <Card className="overflow-hidden p-0">
      <div
        className="flex items-center gap-[18px] px-[26px] py-[26px]"
        style={{ background: verdictSoft(verdict.verdict) }}
      >
        <VerdictStamp verdict={verdict.verdict} size={92} animate />
        <div className="min-w-0">
          <p className="text-[11px] font-bold tracking-[0.12em] text-muted uppercase">Frank says</p>
          <p
            className="mt-1.5 font-display text-[34px] leading-none font-bold tracking-[-0.02em]"
            style={{
              color: `var(--${verdict.verdict === 'your_call' ? 'call' : verdict.verdict})`,
            }}
          >
            {verdictLabel(verdict.verdict)}
          </p>
          <p className="mt-2 text-[16px] font-medium text-ink">{verdict.headline}</p>
        </div>
      </div>
      <div className="flex flex-col gap-4 p-[26px] pt-[18px]">
        {verdict.evidence.length > 0 && (
          <div>
            <div className="mb-3 text-[12px] font-semibold tracking-[0.1em] text-muted uppercase">
              What Frank looked at
            </div>
            <div className="flex flex-col gap-2.5">
              {verdict.evidence.map((e, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{
                      background: `var(--${verdict.verdict === 'your_call' ? 'call' : verdict.verdict})`,
                    }}
                  />
                  <span className="flex-1 text-[14px] text-ink-2">{e.label}</span>
                  <span className="num text-[14px] font-bold whitespace-nowrap text-ink">
                    {e.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        <p className="text-[14px] leading-relaxed text-ink-2">{verdict.reasoning}</p>
        <p className="text-[12px] text-faint">{verdict.disclaimer}</p>
      </div>
    </Card>
  );
}

function StreamingPreview({ partial }: { partial: string }) {
  const preview = previewFromPartial(partial);
  return (
    <Card className="animate-pop flex flex-col gap-4">
      <div className="flex items-center gap-[18px]">
        {preview.verdict ? (
          <VerdictStamp verdict={preview.verdict} size={84} animate />
        ) : (
          <span className="animate-spin-fast inline-block h-[22px] w-[22px] rounded-full border-2 border-line-2 border-t-ink" />
        )}
        <div>
          <p className="text-[11px] font-bold tracking-[0.12em] text-muted uppercase">
            Checking your numbers…
          </p>
          {preview.headline && (
            <p className="mt-1.5 font-display text-[22px] font-bold text-ink">{preview.headline}</p>
          )}
        </div>
      </div>
      {preview.reasoning && (
        <p className="text-[14px] leading-relaxed text-ink-2">
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
        <SectionLabel>You asked, Frank said, you did</SectionLabel>
        <EmptyState title="No questions yet" hint="Ask Frank about a purchase you're weighing." />
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3">
      <SectionLabel>You asked, Frank said, you did</SectionLabel>
      <Card className="p-0">
        {history.data.map((item) => (
          <HistoryRow key={item.id} item={item} />
        ))}
      </Card>
    </section>
  );
}

function HistoryRow({ item }: { item: AdviceHistory }) {
  const setFollowed = useSetFollowed();
  const accent = item.verdict
    ? `var(--${item.verdict === 'your_call' ? 'call' : item.verdict})`
    : 'var(--muted)';
  return (
    <div className="flex items-center gap-4 border-b border-line px-[18px] py-3.5 last:border-0">
      {item.verdict && <VerdictStamp verdict={item.verdict} size={42} label={false} />}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-semibold text-ink">{item.question}</p>
        <p className="text-[12.5px] text-muted">{new Date(item.created_at).toLocaleDateString()}</p>
      </div>
      {item.verdict && (
        <span
          className="rounded-full px-2.5 py-1 text-[12px] font-bold"
          style={{ color: accent, background: verdictSoft(item.verdict) }}
        >
          {verdictLabel(item.verdict)}
        </span>
      )}
      <div className="flex w-[124px] shrink-0 items-center justify-end gap-1.5 text-[12px]">
        {item.user_followed === null ? (
          <>
            <span className="text-muted">Did you?</span>
            <button
              type="button"
              className="rounded-full border border-line-2 px-2.5 py-1 text-ink-2 hover:text-ink"
              onClick={() => setFollowed.mutate({ id: item.id, followed: true })}
            >
              Yes
            </button>
            <button
              type="button"
              className="rounded-full border border-line-2 px-2.5 py-1 text-ink-2 hover:text-ink"
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
    </div>
  );
}
