import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  completeGoogleSignIn,
  logoutEverywhere as logoutEverywhereRequest,
  logoutSession,
  registerAccount,
  verifyCode,
} from '../api/auth';
import {
  BOOTSTRAP_TIMEOUT_MS,
  apiFetch,
  failureReason,
  json,
  refreshAccessToken,
  setAccessToken,
  setSessionExpiredHandler,
} from '../api/client';
import type { TokenOut, User } from '../api/types';
import { pendingHandoff } from '../lib/handoff';
import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext';

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUserState] = useState<User | null>(null);
  const [attempt, setAttempt] = useState(0);
  /** True when a live session ended under us, so login can explain itself. */
  const [expired, setExpired] = useState(false);
  /**
   * Whether this page load landed with a Google handoff to spend.
   *
   * Read during *render*, which is the only place it can be read reliably: a
   * child's effects run before its parent's, so by the time the effect below
   * runs, `AuthCallback` has already taken the fragment out of the URL.
   */
  const handoffPending = useRef(pendingHandoff() !== null);

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

  /** `forget`, plus the parts that only a deliberate sign-out should touch. */
  const forgetLocally = useCallback(() => {
    forget();
    setStatus('anon');
    queryClient.clear();
  }, [forget, queryClient]);

  // A session can end while the app is open — revoked from another device,
  // ended by a password reset, or simply expired. That surfaces as a 401 on
  // some ordinary query, which nothing here would otherwise hear about, leaving
  // the user on a screen whose every panel has quietly failed. Route to login
  // and say so instead.
  useEffect(() => {
    setSessionExpiredHandler(() => {
      setExpired(true);
      forgetLocally();
    });
    return () => setSessionExpiredHandler(null);
  }, [forgetLocally]);

  // On boot, restore a session from the refresh cookie. Every outcome lands on a
  // terminal status — success, 401, 5xx, network error and timeout alike — so
  // there is no path that leaves this on 'loading'. The one that used to escape
  // was a request that never came back at all: with no deadline on the fetch,
  // nothing threw, nothing resolved, and no amount of try/catch/finally here
  // could have noticed. The deadline lives in `api/client`; this just classifies.
  useEffect(() => {
    // Except when a Google handoff is waiting: `AuthCallback` is about to
    // exchange it, and restoring from the cookie alongside that would be exactly
    // the request the handoff exists to avoid — a third-party cookie the browser
    // never sent, answered with a 401 that would set 'anon' and bounce a working
    // sign-in to the login screen. Status stays 'loading', which is what
    // `AuthCallback` is showing anyway.
    if (handoffPending.current) return;
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

  /** Take a freshly minted token and become signed in. */
  const adopt = useCallback(
    async (token: TokenOut) => {
      // Drop any cached data from a prior session so one account never sees
      // another's (e.g. Frankly's daily note, which we keep fresh for an hour).
      queryClient.clear();
      setAccessToken(token.access_token);
      setExpired(false);
      await loadUser();
    },
    [loadUser, queryClient],
  );

  const login = useCallback(
    async (email: string, password: string, remember = false) => {
      const token = await apiFetch<TokenOut>('/auth/login', {
        method: 'POST',
        body: json({ email, password, remember_me: remember }),
      });
      await adopt(token);
    },
    [adopt],
  );

  const completeOAuth = useCallback(
    (handoff: string) => completeGoogleSignIn(handoff).then(adopt),
    [adopt],
  );

  // Back to 'loading' here rather than in the effect: a retry is an event, so the
  // status change belongs with it instead of as a re-render the effect triggers.
  const retry = useCallback(() => {
    // A retry is also how a failed handoff falls back to the cookie, so the
    // handoff has had its one chance by now: clear the flag, or the restore below
    // would skip itself again and the fallback would never make a request.
    handoffPending.current = false;
    setStatus('loading');
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      sessionExpired: expired,
      login,
      // Creates the account and stops. No token exists yet, by design — the
      // caller routes to the code screen, which is where a session can start.
      // The message is passed back rather than swallowed: it says how long
      // until another code may be sent, and the code screen has to honour that.
      register: (email, password) => registerAccount(email, password),
      verify: async (email, code) => adopt(await verifyCode(email, code)),
      completeOAuth,
      // Tell the server first. The refresh cookie is httpOnly, so clearing
      // client state alone would leave a working credential in the jar — which
      // is exactly how signing out used to survive a reload.
      logout: () => {
        void logoutSession().finally(forgetLocally);
      },
      logoutEverywhere: async () => {
        try {
          await logoutEverywhereRequest();
        } finally {
          forgetLocally();
        }
      },
      setUser: setUserState,
      retry,
    }),
    [status, user, expired, login, adopt, completeOAuth, forgetLocally, retry],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
