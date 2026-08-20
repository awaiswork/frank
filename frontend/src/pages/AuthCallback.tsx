import { useEffect, useRef, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { forgetHandoff, pendingHandoff } from '../lib/handoff';

/**
 * Where Google's sign-in lands.
 *
 * The API finished the sign-in and handed this page the session two ways over: a
 * refresh cookie, and a single-use handoff secret in the URL fragment. This
 * spends the handoff, because it is the half that survives a browser blocking
 * third-party cookies — which is Safari, so every browser on iOS, which is why
 * Google sign-in worked on a laptop and failed on a phone.
 *
 * The cookie is the fallback rather than the primary, and it is genuinely a
 * fallback: if the handoff is missing, spent or refused, `retry()` restores from
 * the cookie exactly as this page used to, and lands on login with a reason when
 * that fails too. The access token is never in the URL either way — the handoff
 * buys one over POST, and buys nothing else.
 */
export function AuthCallback() {
  const { status, retry, completeOAuth } = useAuth();
  // Read before the first paint, so the fragment is captured even though the
  // effect below is what strips it.
  const [handoff] = useState(pendingHandoff);
  const started = useRef(false);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    // Once. StrictMode mounts effects twice in development, and the second run
    // would spend a secret the server has already burned.
    if (started.current) return;
    started.current = true;
    // Out of the address bar before the request that spends it: whatever is in
    // the bar is also in this tab's history.
    forgetHandoff();
    if (handoff === null) {
      retry();
      return;
    }
    void completeOAuth(handoff).catch(() => retry());
  }, [handoff, retry, completeOAuth]);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), 3000);
    return () => clearTimeout(timer);
  }, []);

  if (status === 'authed') return <Navigate to="/" replace />;
  // Anything else means neither half of the handover worked. Back to login,
  // which will say so rather than leaving a spinner running.
  if (status === 'anon') return <Navigate to="/login?oauth=failed" replace />;
  if (status === 'unreachable') return <Navigate to="/login?oauth=unreachable" replace />;

  return (
    <div className="grid min-h-svh place-items-center px-6 text-center">
      <div className="flex max-w-[34ch] flex-col items-center gap-3">
        <span className="animate-spin-fast inline-block h-[22px] w-[22px] rounded-full border-2 border-line-2 border-t-ink" />
        <p className="text-[15px] text-muted">
          {slow ? 'Waking the server up — this can take up to a minute.' : 'Signing you in…'}
        </p>
      </div>
    </div>
  );
}
