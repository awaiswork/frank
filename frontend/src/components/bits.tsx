import type { ReactNode } from 'react';

/** "AI" tag on transactions parsed by Frank. */
export function AiBadge() {
  return (
    <span
      title="Parsed by Frank"
      className="shrink-0 rounded-[5px] border border-line-2 px-[5px] py-px text-[9.5px] font-bold tracking-[0.08em] text-go"
    >
      AI
    </span>
  );
}

type Tone = 'go' | 'over' | 'wait' | 'neutral';

/** A lowercase "frank" callout box — the product's voice. */
export function FrankCallout({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  const bg = tone === 'neutral' ? 'var(--surface-2)' : `var(--${tone}-soft)`;
  const accent = tone === 'neutral' ? 'var(--ink)' : `var(--${tone})`;
  return (
    <div
      className="flex items-start gap-[9px] rounded-[10px] px-3 py-2.5"
      style={{ background: bg }}
    >
      <span className="shrink-0 font-display text-[13px] font-bold" style={{ color: accent }}>
        frank
      </span>
      <span className="text-[13px] text-ink">{children}</span>
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
