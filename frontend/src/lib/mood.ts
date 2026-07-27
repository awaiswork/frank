import type { DayMood } from '../api/types';

/**
 * Mood presentation only — the mood itself is decided server-side and arrives on
 * `GET /advisor/daily`.
 *
 * It used to be computed twice (there, and again here from the insights summary),
 * which meant the chip and the ambient glow could disagree on the same screen: the
 * chip read a note cached that morning while the background reacted live. One
 * source now, invalidated whenever money changes.
 */

/** 'unknown' has no colour of its own — we're not making a claim, so stay neutral. */
export function moodColor(mood: DayMood): string {
  return mood === 'unknown' ? 'var(--muted)' : `var(--${mood})`;
}

export function moodSoft(mood: DayMood): string {
  return mood === 'unknown' ? 'var(--surface-2)' : `var(--${mood}-soft)`;
}

export function moodLabel(mood: DayMood): string {
  switch (mood) {
    case 'over':
      return 'over';
    case 'wait':
      return 'ease off';
    case 'unknown':
      return 'set up';
    default:
      return 'on track';
  }
}
