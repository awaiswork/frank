import { describe, expect, it } from 'vitest';
import type { Transaction, TransactionKind } from '../api/types';
import { dayNet } from './net';

const tx = (kind: TransactionKind, amount_cents: number): Transaction => ({
  id: `t-${kind}-${amount_cents}`,
  kind,
  account_id: 'a1',
  counter_account_id: kind === 'transfer' ? 'a2' : null,
  recurring_template_id: null,
  amount_cents,
  currency: 'EUR',
  base_amount_cents: amount_cents,
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

  it('counts a refund as spending given back', () => {
    // Not income — it lifts the day's net by undoing a purchase, and the category
    // aggregate on the server gives back the spend at the same time.
    expect(dayNet([tx('expense', 40_00), tx('refund', 40_00)])).toBe(0);
  });

  it('ignores balance corrections', () => {
    // A reconciliation is the ledger admitting it drifted, not money that arrived or
    // left that day. It moves a balance and nothing else.
    const spending = [tx('expense', 40_00)];
    expect(dayNet([...spending, tx('adjustment_up', 5_00), tx('adjustment_down', 9_00)])).toBe(
      dayNet(spending),
    );
  });

  it('counts what left your account, not the price on the tag', () => {
    // $45 that cost €41.20. Summing the foreign figure would put dollars into a euro
    // total — the client-side twin of the sweep every server aggregate went through.
    const foreign = { ...tx('expense', 45_00), currency: 'USD', base_amount_cents: 41_20 };
    expect(dayNet([foreign])).toBe(-41_20);
  });

  it('is zero for an empty day', () => {
    expect(dayNet([])).toBe(0);
  });
});
