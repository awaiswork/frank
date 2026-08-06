import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { GoogleButton } from '../components/GoogleButton';
import { Mark } from '../components/Logo';
import { Button, Card, Field, TextInput } from '../components/ui';

export function Register() {
  const { status, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === 'authed') return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await register(email, password);
      // No session exists yet — the address has to be proven first. The address
      // travels in router state, not the URL, so it stays out of history.
      void navigate('/verify', { state: { email, purpose: 'verify' } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create account');
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
          <p className="mt-1 text-[14.5px] text-muted">Start tracking what you actually spend.</p>
        </div>
        <Card>
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
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            {error && <p className="text-[13px] text-over">{error}</p>}
            <Button type="submit" disabled={busy}>
              {busy ? 'Creating…' : 'Create account'}
            </Button>
          </form>

          {/* The only sign-up route that works for an address the mail provider
              cannot reach — and it needs no code, because Google has already
              proven the address. */}
          <GoogleButton label="Sign up with Google" />
        </Card>
        <p className="mt-4 text-center text-[13px] text-muted">
          Already have an account?{' '}
          <Link to="/login" className="font-semibold text-ink hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </div>
  );
}
