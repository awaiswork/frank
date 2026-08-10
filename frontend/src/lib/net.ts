import type { Transaction, TransactionKind } from '../api/types';

/**
 * What each kind does to a day's net.
 *
 * The server-side counterpart is `services/accounts.LEG_SIGNS`, guarded by a test
 * that reads the database CHECK constraint. Here the type does that job:
 * `Record<TransactionKind, number>` stops compiling the moment a kind is added, so
 * no kind can fall through to a default.
 *
 * A transfer is 0 because moving your own money between accounts is neither a gain
 * nor a loss on the day it happens. The reducer this replaced read
 * `kind === 'income' ? +x : -x`, which would have counted every transfer as spending.
 */
export const NET_SIGNS: Record<TransactionKind, number> = {
  income: 1,
  expense: -1,
  // Moving your own money is neither a gain nor a loss on the day it happens.
  transfer: 0,
  // A refund undoes spending, so it lifts the day's net back up by what it gives back.
  refund: 1,
  // Corrections are the ledger admitting it drifted, not something that happened to
  // the user's money that day. They move a balance and nothing else.
  adjustment_up: 0,
  adjustment_down: 0,
};

/** Signed total for a day's transactions — income up, spending down, moves neutral. */
export function dayNet(items: readonly Transaction[]): number {
  // base_amount_cents, for the same reason every server aggregate uses it: a day's net
  // adds figures together, and only what actually left your account is comparable. A
  // foreign amount here would put dollars into a euro total.
  return items.reduce((total, t) => total + NET_SIGNS[t.kind] * t.base_amount_cents, 0);
}
