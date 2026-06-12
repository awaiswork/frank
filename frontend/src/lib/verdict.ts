import type { VerdictKind } from '../api/types';

export interface VerdictSpec {
  color: string;
  soft: string;
  label: string;
  dash?: string; // stroke-dasharray; undefined = solid ring
  double?: boolean; // a second inner ring (Skip)
}

/** Per-verdict visual spec — readable without colour via dash pattern + glyph + label. */
export const VERDICT_SPEC: Record<VerdictKind, VerdictSpec> = {
  go: { color: 'var(--go)', soft: 'var(--go-soft)', label: 'Go for it' },
  wait: { color: 'var(--wait)', soft: 'var(--wait-soft)', label: 'Wait', dash: '5 5' },
  skip: {
    color: 'var(--skip)',
    soft: 'var(--skip-soft)',
    label: 'Skip',
    dash: '2 6',
    double: true,
  },
  your_call: { color: 'var(--call)', soft: 'var(--call-soft)', label: 'Your call', dash: '3 5' },
};

export function verdictSoft(verdict: VerdictKind): string {
  return VERDICT_SPEC[verdict].soft;
}

export function verdictLabel(verdict: VerdictKind): string {
  return VERDICT_SPEC[verdict].label;
}
