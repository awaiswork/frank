import { createContext } from 'react';
import type { User } from '../api/types';

export type AuthStatus = 'loading' | 'authed' | 'anon';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setUser: (user: User) => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
