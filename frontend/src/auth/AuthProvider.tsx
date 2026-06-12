import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { apiFetch, json, refreshAccessToken, setAccessToken } from '../api/client';
import type { TokenOut, User } from '../api/types';
import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUserState] = useState<User | null>(null);

  const loadUser = useCallback(async () => {
    const me = await apiFetch<User>('/me');
    setUserState(me);
    setStatus('authed');
  }, []);

  // On boot, try to restore a session from the refresh cookie.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const ok = await refreshAccessToken();
      if (cancelled) return;
      if (!ok) {
        setStatus('anon');
        return;
      }
      try {
        await loadUser();
      } catch {
        if (!cancelled) setStatus('anon');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadUser]);

  const authenticate = useCallback(
    async (path: '/auth/login' | '/auth/register', email: string, password: string) => {
      const token = await apiFetch<TokenOut>(path, {
        method: 'POST',
        body: json({ email, password }),
      });
      setAccessToken(token.access_token);
      await loadUser();
    },
    [loadUser],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      login: (email, password) => authenticate('/auth/login', email, password),
      register: (email, password) => authenticate('/auth/register', email, password),
      logout: () => {
        setAccessToken(null);
        setUserState(null);
        setStatus('anon');
      },
      setUser: setUserState,
    }),
    [status, user, authenticate],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
