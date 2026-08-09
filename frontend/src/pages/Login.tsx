import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { resendCode } from '../api/auth';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { GoogleButton } from '../components/GoogleButton';
import { Mark } from '../components/Logo';
import { Button, Card, Field, TextInput } from '../components/ui';

/** What came back from an OAuth round trip that didn't end in a session. */
const OAUTH_MESSAGES: Record<string, string> = {
  cancelled: 'Google sign-in was cancelled.',
  expired: 'That sign-in took too long. Try again.',
  failed: "Google sign-in didn't work. Try again, or use your password.",
  unreachable: "I couldn't reach the server after Google. Try again in a moment.",
};

export function Login() {
  const { status, login, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === 'authed') return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password, remember);
      navigate('/');
    } catch (err) {
      // 403 is not a failure to show — it means the password was right and the
      // address still needs proving. Send them to the code screen instead.
      if (err instanceof ApiError && err.status === 403) {
        // Ask for the code here, because /auth/login deliberately doesn't send
        // one: it raises, and a background task attached to a raised response is
        // discarded silently. Without this the code screen announced "I've sent
        // a six-digit code to you" over an inbox where nothing had been sent.
        let retryAfter: number | null = null;
        try {
          retryAfter = (await resendCode(email, 'verify')).retry_after_seconds;
        } catch {
          // Throttled, or the server went away between the two calls. Land on
          // the code screen with its resend button live rather than stranding
          // someone on the login form — that button is the recovery path.
        }
        void navigate('/verify', { state: { email, purpose: 'verify', retryAfter } });
        return;
      }
      setError(err instanceof ApiError ? err.message : 'Could not log in');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-svh place-items-center px-4">
      <div className="w-full max-w-sm animate-fade-up">
        <div className="mb-6 flex flex-col items-center text-center">
          <Mark size={52} />
          <h1 className="mt-3.5 font-display text-[34px] font-bold text-ink">Frankly</h1>
          <p className="mt-1 text-[14.5px] text-muted">Honest advice on what you can spend.</p>
        </div>
        <Card>
          {OAUTH_MESSAGES[params.get('oauth') ?? ''] && (
            <p className="mb-4 rounded-[10px] bg-wait-soft px-3 py-2.5 text-[13.5px] leading-relaxed text-ink-2">
              {OAUTH_MESSAGES[params.get('oauth') ?? '']}
            </p>
          )}
          {sessionExpired && (
            <p className="mb-4 rounded-[10px] bg-wait-soft px-3 py-2.5 text-[13.5px] leading-relaxed text-ink-2">
              You were signed out — the session ended or was signed out from another device.
            </p>
          )}
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <Field label="Email">
              <TextInput
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </Field>
            <Field label="Password">
              <TextInput
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            {/* Lifetime only — 12 hours by default, 30 days when ticked. It
                changes nothing about how the cookie is secured. */}
            <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[14px] text-ink-2">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="h-[18px] w-[18px] shrink-0 accent-[var(--ink)]"
              />
              Keep me signed in on this device
            </label>
            {error && <p className="text-[13px] text-over">{error}</p>}
            <Button type="submit" disabled={busy}>
              {busy ? 'Logging in…' : 'Log in'}
            </Button>
          </form>

          <GoogleButton label="Continue with Google" />
        </Card>
        <p className="mt-4 text-center text-[13px] text-muted">
          <Link to="/forgot-password" className="font-semibold text-ink-2 hover:underline">
            Forgotten your password?
          </Link>
        </p>
        <p className="mt-2 text-center text-[13px] text-muted">
          New here?{' '}
          <Link to="/register" className="font-semibold text-ink hover:underline">
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}
