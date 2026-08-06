/**
 * Whether a given account has been through first-run setup.
 *
 * Kept per user, not per browser. It used to be one global
 * `frankly-onboarded` flag, which meant that once *anyone* finished or skipped
 * setup on a machine, every account created there afterwards skipped it too —
 * silently, with no way to get back. Google sign-in turned that from a corner
 * case into the common one, because making a second account is now a single
 * click on a browser that has almost certainly seen the app before.
 *
 * Still localStorage rather than a column: this records "I dismissed the
 * prompt", which is a property of a device, not of an account. Someone who
 * skips on their laptop should reasonably see it once on their phone.
 */

const PREFIX = 'frankly-onboarded';

const key = (userId: string) => `${PREFIX}:${userId}`;

export function hasOnboarded(userId: string): boolean {
  try {
    return localStorage.getItem(key(userId)) !== null;
  } catch {
    // Private mode, or storage disabled. Showing setup again is the safe way to
    // be wrong — the alternative is hiding it from someone who never saw it.
    return false;
  }
}

export function markOnboarded(userId: string): void {
  try {
    localStorage.setItem(key(userId), '1');
  } catch {
    /* nothing to do; the prompt reappears next time, which is harmless */
  }
}
