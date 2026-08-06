import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { resetPassword } from '../api/auth';
import { ApiError } from '../api/client';
import { Mark } from '../components/Logo';
import { Button, Card, Field, TextInput } from '../components/ui';

/** Same floor as registration. Kept beside the form so the two can't silently
 *  drift into disagreeing about what a valid password is. */
const MIN_PASSWORD = 8;

/** Step two of the reset. The ticket arrives in router state from the code
 *  screen — never in the URL, because it is a credential and URLs are kept. */
interface TicketState {
  ticket?: string;
}

export function ResetPassword() {
  const location = useLocation();
  const navigate = useNavigate();
  const ticket = ((location.state ?? {}) as TicketState).ticket ?? '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dead, setDead] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = confirm.length > 0 && confirm !== password;
  const ready = password.length >= MIN_PASSWORD && confirm === password && !busy;

  // Arriving without a ticket means a refresh, a bookmark, or someone guessing
  // the route. There is nothing to reset against, so start over.
  if (!ticket && !done) return <Navigate to="/forgot-password" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(ticket, password);
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) setDead(true);
      else if (err instanceof ApiError && err.status === 422)
        setError(`Pick a password of at least ${MIN_PASSWORD} characters.`);
      else setError("I couldn't reach the server. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-svh place-items-center px-4 py-10">
      <div className="animate-fade-up w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <Mark size={52} />
          <h1 className="mt-3.5 font-display text-[28px] font-bold text-ink">
            {done ? 'Password set' : 'Choose a new password'}
          </h1>
        </div>

        <Card>
          {dead && (
            <div className="flex flex-col gap-4">
              <p className="text-[15px] leading-relaxed text-ink-2">
                That reset has expired. Codes last ten minutes and work once, so this one has either
                run out or already been used.
              </p>
              <Link
                to="/forgot-password"
                className="inline-flex h-11 items-center justify-center rounded-input bg-ink px-5 text-[14.5px] font-semibold text-paper hover:opacity-90"
              >
                Start again
              </Link>
            </div>
          )}

          {done && !dead && (
            <div className="flex flex-col gap-4">
              <p className="text-[15px] leading-relaxed text-ink-2">
                Done. I've also signed you out everywhere else — if someone else had got in, they're
                out now.
              </p>
              <Button onClick={() => void navigate('/login', { replace: true })}>Sign in</Button>
            </div>
          )}

          {!done && !dead && (
            <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
              <Field label="New password">
                <TextInput
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-describedby="pw-rule"
                  required
                />
              </Field>
              <p id="pw-rule" className="-mt-2 text-[13px] text-muted">
                At least {MIN_PASSWORD} characters.
              </p>
              <Field label="Again, to be sure">
                <TextInput
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
              </Field>
              {tooShort && (
                <p className="text-[13px] text-over">That's under {MIN_PASSWORD} characters.</p>
              )}
              {mismatch && <p className="text-[13px] text-over">Those two don't match.</p>}
              {error && <p className="text-[13px] text-over">{error}</p>}
              <Button type="submit" disabled={!ready}>
                {busy ? 'Saving…' : 'Set my password'}
              </Button>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}
