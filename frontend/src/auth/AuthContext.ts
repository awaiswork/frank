import { createContext } from 'react';
import type { User } from '../api/types';

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
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setUser: (user: User) => void;
  /** Re-run session restore, for the retry button on the unreachable screen. */
  retry: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
