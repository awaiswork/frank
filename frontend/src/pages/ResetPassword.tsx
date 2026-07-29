import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { resetPassword } from '../api/auth';
import { ApiError } from '../api/client';
import { Mark } from '../components/Logo';
import { Button, Card, Field, TextInput } from '../components/ui';

/** Same floor as registration. Kept here rather than imported so the two can't
 *  silently drift into disagreeing about what a valid password is. */
const MIN_PASSWORD = 8;

type State = 'form' | 'done' | 'dead-link';

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const navigate = useNavigate();

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [state, setState] = useState<State>(token ? 'form' : 'dead-link');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;
  const mismatch = confirm.length > 0 && confirm !== password;
  const ready = password.length >= MIN_PASSWORD && confirm === password && !busy;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      setState('done');
    } catch (err) {
      // 400 is the server's single answer for expired, already-used, tampered
      // and unknown — it will not say which, and neither will this page.
      if (err instanceof ApiError && err.status === 400) setState('dead-link');
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
            {state === 'done' ? 'Password set' : 'Choose a new password'}
          </h1>
        </div>

        <Card>
          {state === 'dead-link' && (
            <div className="flex flex-col gap-4">
              <p className="text-[15px] leading-relaxed text-ink-2">
                That link doesn't work any more. Reset links last an hour and can only be used once,
                so this one has either expired or already been used.
              </p>
              <Link
                to="/forgot-password"
                className="inline-flex h-11 items-center justify-center rounded-input bg-ink px-5 text-[14.5px] font-semibold text-paper hover:opacity-90"
              >
                Send me a new one
              </Link>
            </div>
          )}

          {state === 'done' && (
            <div className="flex flex-col gap-4">
              <p className="text-[15px] leading-relaxed text-ink-2">
                Done. I've also signed out everywhere else — if someone else had got in, they're out
                now.
              </p>
              <Button onClick={() => void navigate('/login')}>Sign in</Button>
            </div>
          )}

          {state === 'form' && (
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
