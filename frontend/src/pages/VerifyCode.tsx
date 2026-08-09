import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { resendCode, verifyResetCode, type CodePurpose } from '../api/auth';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Mark } from '../components/Logo';
import { Button, Card, TextInput } from '../components/ui';

/** Passed through router state rather than the URL — a code screen bookmarked
 *  with an address in the query string is an address in someone's history. */
interface CodeState {
  email?: string;
  purpose?: CodePurpose;
  /**
   * Seconds until another code may be sent, when the screen that routed here
   * just caused one to go out. Absent means nothing was sent and the resend
   * button should be live immediately.
   *
   * This exists because the server *cannot* tell us. `/auth/resend-code` answers
   * identically whether it sent a code or declined on cooldown — that sameness is
   * what stops the endpoint confirming an address is registered — so the honest
   * moment to start the clock is the one send we witnessed ourselves.
   */
  retryAfter?: number | null;
}

const COPY = {
  verify: {
    title: 'Check your email',
    lead: "I've sent a six-digit code to",
    submit: 'Confirm',
  },
  reset: {
    title: 'Enter the code',
    lead: 'If that address has an account, a six-digit code is on its way to',
    submit: 'Continue',
  },
} as const;

export function VerifyCode() {
  const location = useLocation();
  const navigate = useNavigate();
  const { verify, status } = useAuth();

  const state = (location.state ?? {}) as CodeState;
  const email = state.email ?? '';
  const purpose: CodePurpose = state.purpose ?? 'verify';

  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Starts held down when a code has just been sent, so the button never offers
  // a send the server is going to decline in silence.
  const [cooldown, setCooldown] = useState(() => state.retryAfter ?? 0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  // Landing here without an address means a refresh or a pasted URL; there is
  // nothing to verify against, so start over rather than show a dead form.
  if (!email)
    return <Navigate to={purpose === 'reset' ? '/forgot-password' : '/register'} replace />;
  if (status === 'authed') return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (purpose === 'verify') {
        await verify(email, code);
        void navigate('/', { replace: true });
      } else {
        const { ticket } = await verifyResetCode(email, code);
        // The ticket travels in router state, never the URL — it is a
        // credential, and URLs end up in history and Referer headers.
        void navigate('/reset-password', { replace: true, state: { ticket } });
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "I couldn't reach the server. Try again in a moment.",
      );
      setCode('');
      inputRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      const res = await resendCode(email, purpose);
      // The server's own sentence, not one of ours. It is written to be true
      // whether or not the address is registered, and it cannot drift from what
      // the endpoint actually did. This used to read "Sent. It can take a minute
      // to arrive." — asserted by the client, and false every time the cooldown
      // had quietly suppressed the send.
      setNotice(res.detail);
      setCooldown(res.retry_after_seconds ?? 60);
    } catch {
      setError("I couldn't reach the server. Try again in a moment.");
    }
  }

  return (
    <div className="grid min-h-svh place-items-center px-4 py-10">
      <div className="animate-fade-up w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <Mark size={52} />
          <h1 className="mt-3.5 font-display text-[28px] font-bold text-ink">
            {COPY[purpose].title}
          </h1>
        </div>
        <Card>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <p className="text-[14.5px] leading-relaxed text-ink-2">
              {COPY[purpose].lead} <span className="font-semibold text-ink">{email}</span>. It works
              for the next 10 minutes.
            </p>
            <TextInput
              ref={inputRef}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              // A numeric keypad on phones, and the OS one-time-code autofill on
              // iOS and Android — which is most of why this is a code at all.
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              aria-label="Six-digit code"
              placeholder="000000"
              className="num text-center !text-[26px] tracking-[0.4em]"
              required
            />
            {error && <p className="text-[13px] text-over">{error}</p>}
            {notice && !error && <p className="text-[13px] text-muted">{notice}</p>}
            <Button type="submit" disabled={busy || code.length !== 6}>
              {busy ? 'Checking…' : COPY[purpose].submit}
            </Button>
          </form>
          <button
            type="button"
            onClick={() => void resend()}
            disabled={cooldown > 0}
            className="mt-4 h-11 w-full text-[13.5px] font-semibold text-ink-2 underline underline-offset-2 disabled:no-underline disabled:opacity-55"
          >
            {cooldown > 0 ? `Send another in ${cooldown}s` : 'Send another code'}
          </button>
        </Card>
        <p className="mt-4 text-center text-[13px] text-muted">
          Wrong address?{' '}
          <Link
            to={purpose === 'reset' ? '/forgot-password' : '/register'}
            className="font-semibold text-ink hover:underline"
          >
            Start again
          </Link>
        </p>
      </div>
    </div>
  );
}
