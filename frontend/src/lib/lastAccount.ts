/**
 * The account the capture sheet should open on.
 *
 * Per user, like [[onboarding]] and for the same reason: two people sharing a
 * browser must not inherit each other's default. Still localStorage rather than a
 * column, because "the one I usually pay from" is a habit of a device — a phone in a
 * pocket and a laptop at a desk reasonably differ — and getting it wrong costs one
 * tap, not a wrong number.
 */

const PREFIX = 'frankly-last-account';

const key = (userId: string) => `${PREFIX}:${userId}`;

export function lastAccount(userId: string): string | null {
  try {
    return localStorage.getItem(key(userId));
  } catch {
    return null;
  }
}

export function rememberAccount(userId: string, accountId: string): void {
  try {
    localStorage.setItem(key(userId), accountId);
  } catch {
    /* private mode; the picker just opens on the first account next time */
  }
}
