import { useEffect, useRef, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

/**
 * Where Google's sign-in lands.
 *
 * The API set the refresh cookie on its redirect and put nothing in the URL —
 * an access token in a query string ends up in history, in `Referer` headers
 * and in server logs. So there is nothing to read here: the app simply asks the
 * provider to restore the session it already has a cookie for, which is the
 * same path a normal page load takes.
 */
export function AuthCallback() {
  const { status, retry } = useAuth();
  const started = useRef(false);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    // Once. StrictMode mounts effects twice in development, and a second
    // restore would rotate the refresh token underneath the first.
    if (started.current) return;
    started.current = true;
    retry();
  }, [retry]);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), 3000);
    return () => clearTimeout(timer);
  }, []);

  if (status === 'authed') return <Navigate to="/" replace />;
  // Anything else means the cookie didn't survive the round trip. Back to
  // login, which will say so rather than leaving a spinner running.
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
