import type { DayMood, InsightsSummary } from '../api/types';

/**
 * Live "money weather" for the ambient field — recomputed as the user logs, so the
 * background shifts in real time. Mirrors the server's daily-note mood logic (minus
 * per-budget pace, which the insights summary doesn't carry): over once you're past
 * safe-to-spend, wait when the current burn would blow the days left, else go.
 */
export function dayMoodFromInsights(summary: InsightsSummary | undefined): DayMood {
  if (!summary) return 'go';
  const sts = summary.safe_to_spend.safe_to_spend_cents;
  if (sts < 0) return 'over';
  const now = new Date();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const daysLeft = Math.max(daysInMonth - now.getDate(), 0);
  const projected = summary.daily_burn.daily_burn_cents * daysLeft;
  if (sts - projected < 0) return 'wait';
  return 'go';
}

export function moodColor(mood: DayMood): string {
  return `var(--${mood})`;
}

export function moodSoft(mood: DayMood): string {
  return `var(--${mood}-soft)`;
}

export function moodLabel(mood: DayMood): string {
  return mood === 'over' ? 'over' : mood === 'wait' ? 'ease off' : 'on track';
}
