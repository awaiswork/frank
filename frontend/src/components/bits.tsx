import type { ReactNode } from 'react';

/** "AI" tag on transactions parsed by Frankly. */
export function AiBadge() {
  return (
    <span
      title="Parsed by Frankly"
      className="shrink-0 rounded-[5px] border border-line-2 px-[5px] py-px text-[9.5px] font-bold tracking-[0.08em] text-go"
    >
      AI
    </span>
  );
}

/** Marks a feature that's built but switched off in this build. */
export function ComingSoonBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`shrink-0 rounded-full border border-line-2 bg-inset px-2.5 py-1 text-[11px] font-bold tracking-[0.08em] text-muted uppercase ${className}`}
    >
      Coming soon
    </span>
  );
}

type Tone = 'go' | 'over' | 'wait' | 'neutral';

/** A lowercase "frankly" callout box — the product's voice. */
export function FranklyCallout({
  tone = 'neutral',
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  const bg = tone === 'neutral' ? 'var(--surface-2)' : `var(--${tone}-soft)`;
  const accent = tone === 'neutral' ? 'var(--ink)' : `var(--${tone})`;
  return (
    <div
      className="flex items-start gap-[9px] rounded-[10px] px-3 py-2.5"
      style={{ background: bg }}
    >
      <span className="shrink-0 font-display text-[13px] font-bold" style={{ color: accent }}>
        frankly
      </span>
      <span className="text-[13px] text-ink">{children}</span>
    </div>
  );
}

/**
 * A failed panel, with a way out. Requests carry a deadline now, so a sleeping
 * API surfaces here as an error rather than a spinner that never stops — which
 * only helps if there's something to press.
 */
export function RetryLine({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px] text-muted">
      <span>{message}</span>
      <button
        type="button"
        onClick={onRetry}
        className="font-semibold text-ink-2 underline underline-offset-2 hover:text-ink"
      >
        Try again
      </button>
    </div>
  );
}

/** Soft breathing status dot. */
export function BreathingDot({ color = 'var(--go)' }: { color?: string }) {
  return (
    <span
      className="animate-breathe inline-block h-[7px] w-[7px] rounded-full"
      style={{ background: color }}
    />
  );
}
