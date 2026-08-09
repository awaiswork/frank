import { createContext } from 'react';
import type { AuthMessage, User } from '../api/types';

/**
 * 'anon' and 'unreachable' are deliberately separate. 'anon' means the API told
 * us the session is over, and the answer is the login screen. 'unreachable'
 * means we never got an answer — a sleeping instance, a 5xx, a dead connection —
 * and the answer is a retry. Routing the second case to login would ask someone
 * to sign in against a server that cannot sign them in.
 */
export type AuthStatus = 'loading' | 'authed' | 'anon' | 'unreachable';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  /** A session ended while the app was open, rather than never having existed. */
  sessionExpired: boolean;
  /** `remember` picks the session lifetime — 12 hours, or 30 days. */
  login: (email: string, password: string, remember?: boolean) => Promise<void>;
  /**
   * Create the account. Resolves with no session: registration proves nothing
   * about the address, so the caller sends the user to the code screen.
   *
   * Resolves with the server's message rather than void, because it carries
   * `retry_after_seconds` — the code screen needs it to know a code has just
   * gone out, and therefore that its resend button must not offer another yet.
   */
  register: (email: string, password: string) => Promise<AuthMessage>;
  /** Redeem a signup code. This is where an email account's session begins. */
  verify: (email: string, code: string) => Promise<void>;
  logout: () => void;
  logoutEverywhere: () => Promise<void>;
  setUser: (user: User) => void;
  /** Re-run session restore, for the retry button on the unreachable screen. */
  retry: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
