import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  BOOTSTRAP_TIMEOUT_MS,
  apiFetch,
  failureReason,
  json,
  refreshAccessToken,
  setAccessToken,
} from '../api/client';
import type { TokenOut, User } from '../api/types';
import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext';

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUserState] = useState<User | null>(null);
  const [attempt, setAttempt] = useState(0);

  const loadUser = useCallback(async () => {
    const me = await apiFetch<User>('/me');
    setUserState(me);
    setStatus('authed');
  }, []);

  /** Drop every trace of a session we no longer have. */
  const forget = useCallback(() => {
    setAccessToken(null);
    setUserState(null);
  }, []);

  // On boot, restore a session from the refresh cookie. Every outcome lands on a
  // terminal status — success, 401, 5xx, network error and timeout alike — so
  // there is no path that leaves this on 'loading'. The one that used to escape
  // was a request that never came back at all: with no deadline on the fetch,
  // nothing threw, nothing resolved, and no amount of try/catch/finally here
  // could have noticed. The deadline lives in `api/client`; this just classifies.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const restored = await refreshAccessToken(BOOTSTRAP_TIMEOUT_MS);
      if (cancelled) return;
      if (!restored.ok) {
        forget();
        setStatus(restored.reason === 'unauthenticated' ? 'anon' : 'unreachable');
        return;
      }
      try {
        const me = await apiFetch<User>('/me', {}, BOOTSTRAP_TIMEOUT_MS);
        if (cancelled) return;
        setUserState(me);
        setStatus('authed');
      } catch (err) {
        if (cancelled) return;
        forget();
        setStatus(failureReason(err) === 'unauthenticated' ? 'anon' : 'unreachable');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt, forget]);

  const authenticate = useCallback(
    async (path: '/auth/login' | '/auth/register', email: string, password: string) => {
      // Drop any cached data from a prior session so one account never sees
      // another's (e.g. Frankly's daily note, which we keep fresh for an hour).
      queryClient.clear();
      const token = await apiFetch<TokenOut>(path, {
        method: 'POST',
        body: json({ email, password }),
      });
      setAccessToken(token.access_token);
      await loadUser();
    },
    [loadUser, queryClient],
  );

  // Back to 'loading' here rather than in the effect: a retry is an event, so the
  // status change belongs with it instead of as a re-render the effect triggers.
  const retry = useCallback(() => {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }, []);

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
        queryClient.clear();
      },
      setUser: setUserState,
      retry,
    }),
    [status, user, authenticate, queryClient, retry],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
