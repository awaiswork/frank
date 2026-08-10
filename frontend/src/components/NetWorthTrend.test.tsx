// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { NetWorth } from '../api/types';
import { formatMoney } from '../lib/money';
import { NetWorthTrend } from './NetWorthTrend';

afterEach(cleanup);

const point = (on: string, total: number) => ({
  on,
  accounts_cents: total,
  assets_cents: 0,
  total_cents: total,
});

/** Nothing known before June, then a car appears and the line steps up. */
const withLateAsset: NetWorth = {
  points: [
    point('2026-04-30', 1_000_00),
    point('2026-05-31', 1_000_00),
    point('2026-06-30', 9_000_00),
    point('2026-07-31', 9_200_00),
  ],
  complete_from: '2026-06-30',
};

describe('NetWorthTrend', () => {
  it('measures the change only where the line is comparable', () => {
    // From the first point it would read "up 8 200,00 €", almost all of which is a
    // car being entered rather than money being made — the summary asserting exactly
    // what the dashed section exists to warn against.
    render(<NetWorthTrend data={withLateAsset} />);
    // Built with formatMoney rather than typed out: it separates thousands with a thin
    // space and precedes € with a non-breaking one, so a hand-written literal looks
    // identical and does not match.
    expect(document.body.textContent).toContain(`Up ${formatMoney(200_00)}`);
    expect(document.body.textContent).toContain('since June 2026');
    expect(document.body.textContent).not.toContain(formatMoney(8_200_00));
  });

  it('draws the incomplete stretch separately and says why', () => {
    render(<NetWorthTrend data={withLateAsset} />);
    const dashed = document.querySelectorAll('polyline[stroke-dasharray]');
    expect(dashed).toHaveLength(1);
    expect(document.body.textContent).toContain('before everything here was on file');
  });

  it('says so rather than comparing when only one point is comparable', () => {
    render(<NetWorthTrend data={{ ...withLateAsset, complete_from: '2026-07-31' }} />);
    expect(document.body.textContent).toContain('Not enough history to compare yet');
  });

  it('needs no dashed section when everything was always known', () => {
    render(<NetWorthTrend data={{ ...withLateAsset, complete_from: null }} />);
    expect(document.querySelectorAll('polyline[stroke-dasharray]')).toHaveLength(0);
    expect(document.body.textContent).not.toContain('before everything here was on file');
  });
});
