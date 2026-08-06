import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { forgotPassword } from '../api/auth';
import { Mark } from '../components/Logo';
import { Button, Card, Field, TextInput } from '../components/ui';

/**
 * Ask for a reset link.
 *
 * The confirmation is the same whether or not the address has an account —
 * that's the whole point of the endpoint, and the UI must not undo it by, say,
 * showing a different message for an unknown address. There is deliberately no
 * error state for "no such user", because the page is never told.
 */
export function ForgotPassword() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await forgotPassword(email);
      // Straight to the code screen. The wording there is deliberately
      // conditional ("if that address has an account") because this endpoint
      // will not say whether it does.
      void navigate('/verify', { state: { email, purpose: 'reset' } });
    } catch {
      // Only a transport or throttling failure can land here.
      setError("I couldn't reach the server. Try again in a moment.");
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
            Reset your password
          </h1>
        </div>
        <Card>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <p className="text-[14.5px] leading-relaxed text-ink-2">
              Tell me the address you signed up with and I'll send a code.
            </p>
            <Field label="Email">
              <TextInput
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </Field>
            {error && <p className="text-[13px] text-over">{error}</p>}
            <Button type="submit" disabled={busy || !email.trim()}>
              {busy ? 'Sending…' : 'Send me a code'}
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-[13px] text-muted">
          Remembered it?{' '}
          <Link to="/login" className="font-semibold text-ink hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
