import { describe, expect, it } from 'vitest';
import type { Transaction, TransactionKind } from '../api/types';
import { dayNet } from './net';

const tx = (kind: TransactionKind, amount_cents: number): Transaction => ({
  id: `t-${kind}-${amount_cents}`,
  kind,
  account_id: 'a1',
  counter_account_id: kind === 'transfer' ? 'a2' : null,
  amount_cents,
  description: 'x',
  merchant: null,
  occurred_on: '2026-08-10',
  category_id: null,
  source: 'manual',
  created_at: '2026-08-10T00:00:00Z',
});

describe('dayNet', () => {
  it('counts income up and spending down', () => {
    expect(dayNet([tx('income', 300_00), tx('expense', 40_00)])).toBe(260_00);
  });

  it('ignores transfers, whichever way they run', () => {
    // The client-side counterpart of the server's conservation property: moving your
    // own money is not a gain or a loss, so a day's net cannot notice it happened.
    const spending = [tx('income', 300_00), tx('expense', 40_00)];
    expect(dayNet([...spending, tx('transfer', 500_00)])).toBe(dayNet(spending));
  });

  it('is zero for a day of nothing but moves', () => {
    // The old reducer read `income ? +x : -x`, which made this −7500.
    expect(dayNet([tx('transfer', 50_00), tx('transfer', 25_00)])).toBe(0);
  });

  it('is zero for an empty day', () => {
    expect(dayNet([])).toBe(0);
  });
});
