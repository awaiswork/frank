import { useDailyNote } from '../api/hooks';
import type { DayMood } from '../api/types';
import { moodColor, moodLabel } from '../lib/mood';
import { BreathingDot } from './bits';
import { Card } from './ui';

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

/**
 * Frank's daily check-in — the home hero and the app's reason to open daily. One
 * opinionated, AI-written line grounded in today's real numbers, with the day's
 * mood (which also drives the ambient field) and a quiet streak.
 */
export function FrankDaily() {
  const daily = useDailyNote();
  const today = new Date();
  const dateLong = today.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });

  const d = daily.data;
  const mood: DayMood = d?.mood ?? 'go';
  const color = moodColor(mood);

  return (
    <Card
      className="animate-fade-up relative overflow-hidden"
      style={{
        background: `linear-gradient(165deg, color-mix(in oklab, ${color} 8%, var(--surface)) 0%, var(--surface) 58%)`,
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[13px] font-medium text-muted">{greeting()}</div>
          <div className="mt-0.5 font-display text-[19px] font-semibold tracking-[-0.01em] text-ink-2">
            {dateLong}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {d && d.streak >= 2 && <StreakChip days={d.streak} color={color} />}
          <span
            className="flex items-center gap-[7px] rounded-full border border-line px-2.5 py-1 text-[11px] font-bold tracking-[0.1em] uppercase"
            style={{ color }}
          >
            <BreathingDot color={color} />
            {moodLabel(mood)}
          </span>
        </div>
      </div>

      <div className="mt-5">
        {daily.isLoading ? (
          <div className="flex items-center gap-2.5 text-[15px] text-muted">
            <span className="animate-spin-fast inline-block h-[18px] w-[18px] rounded-full border-2 border-line-2 border-t-ink" />
            Frank's reading your numbers…
          </div>
        ) : d ? (
          <>
            <p
              className="font-display text-[23px] leading-[1.18] font-semibold tracking-[-0.02em] text-balance"
              style={{ color }}
            >
              {d.headline}
            </p>
            <p className="mt-2 max-w-[54ch] text-[15.5px] leading-relaxed text-ink-2 text-pretty">
              {d.note}
            </p>
            <p className="mt-2.5 font-display text-[12.5px] font-bold text-muted">— frank</p>
          </>
        ) : (
          <p className="text-[15px] text-muted">
            Frank's note is taking a moment — log something and check back.
          </p>
        )}
      </div>
    </Card>
  );
}

function StreakChip({ days, color }: { days: number; color: string }) {
  return (
    <span
      className="flex items-center gap-1 rounded-full bg-inset px-2.5 py-1 text-[12px] font-bold"
      title={`${days}-day streak with Frank`}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill={color} aria-hidden="true">
        <path d="M13 2c.4 3-2 4.2-2 6.6A2.4 2.4 0 0 0 13.4 11c1-.7 1.1-1.9 1.1-1.9 1.7 1.3 3 3.3 3 5.6a5.5 5.5 0 1 1-11 0c0-3.3 2.6-4.9 3.1-8.2C9.9 4.4 11.1 2.9 13 2z" />
      </svg>
      <span className="num" style={{ color }}>
        {days}
      </span>
    </span>
  );
}
