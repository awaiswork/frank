import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { resendVerification, verifyEmail } from '../api/auth';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Mark } from '../components/Logo';
import { Button, Card } from '../components/ui';

type State = 'working' | 'ok' | 'already' | 'dead-link' | 'unreachable';

/**
 * The page the emailed link lands on.
 *
 * Runs the exchange once on mount. The guard matters under StrictMode, which
 * mounts effects twice in development: without it the second run would redeem a
 * token the first had already consumed, and a successful verification would
 * render as a dead link.
 */
export function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const { user, setUser } = useAuth();
  const [state, setState] = useState<State>(token ? 'working' : 'dead-link');
  const [resent, setResent] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;

    let cancelled = false;
    void (async () => {
      try {
        await verifyEmail(token);
        if (cancelled) return;
        setState('ok');
        // Clear the banner immediately rather than waiting for a refetch.
        if (user) setUser({ ...user, email_verified: true });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 400) {
          setState(user?.email_verified ? 'already' : 'dead-link');
        } else {
          setState('unreachable');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // `user` is deliberately absent: this must run once, on the token.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function resend() {
    try {
      const res = await resendVerification();
      setResent(
        res.retry_after_seconds && res.detail.includes('already sent')
          ? `Already sent one — try again in ${res.retry_after_seconds}s.`
          : 'Sent. Check your inbox.',
      );
    } catch {
      setResent("I couldn't reach the server. Try again in a moment.");
    }
  }

  const copy: Record<State, { title: string; body: string }> = {
    working: { title: 'Confirming…', body: 'One moment.' },
    ok: {
      title: 'Email confirmed',
      body: "That's your address confirmed. Nothing else to do.",
    },
    already: {
      title: 'Already confirmed',
      body: 'This address was confirmed already, so the link had nothing left to do.',
    },
    'dead-link': {
      title: 'That link has expired',
      body: 'Confirmation links last 24 hours and work once. Sign in and I can send a fresh one.',
    },
    unreachable: {
      title: "I can't reach the server",
      body: 'It may still be waking up. Your link is fine — try again in a moment.',
    },
  };

  return (
    <div className="grid min-h-svh place-items-center px-4 py-10">
      <div className="animate-fade-up w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <Mark size={52} />
          <h1 className="mt-3.5 font-display text-[28px] font-bold text-ink">
            {copy[state].title}
          </h1>
        </div>
        <Card>
          <div className="flex flex-col gap-4">
            <p className="text-[15px] leading-relaxed text-ink-2">{copy[state].body}</p>

            {state === 'unreachable' && (
              <Button onClick={() => window.location.reload()}>Try again</Button>
            )}

            {state === 'dead-link' && user && (
              <>
                <Button variant="secondary" onClick={() => void resend()}>
                  Send a new link
                </Button>
                {resent && <p className="text-[13px] text-muted">{resent}</p>}
              </>
            )}

            {(state === 'ok' || state === 'already') && (
              <Link
                to="/"
                className="inline-flex h-11 items-center justify-center rounded-input bg-ink px-5 text-[14.5px] font-semibold text-paper hover:opacity-90"
              >
                Go to Frankly
              </Link>
            )}

            {state === 'dead-link' && !user && (
              <Link
                to="/login"
                className="inline-flex h-11 items-center justify-center rounded-input bg-ink px-5 text-[14.5px] font-semibold text-paper hover:opacity-90"
              >
                Sign in
              </Link>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
