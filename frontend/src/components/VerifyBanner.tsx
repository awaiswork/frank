import { useEffect, useState } from 'react';
import { resendVerification } from '../api/auth';
import { useAuth } from '../auth/useAuth';

const DISMISSED_KEY = 'frankly-verify-dismissed';

/**
 * The nudge for an unconfirmed address.
 *
 * Soft gate, on purpose: it sits above the page and can be dismissed, and
 * nothing behind it is locked. Someone who mistypes their address at signup
 * still gets to see and log their own money — being shut out of your finances
 * over an unread email would be a worse failure than an unverified address.
 *
 * Dismissal lasts the session (sessionStorage), so it comes back tomorrow
 * without nagging on every screen today.
 */
export function VerifyBanner() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return sessionStorage.getItem(DISMISSED_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [message, setMessage] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((n) => n - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  if (!user || user.email_verified || dismissed) return null;

  const dismiss = () => {
    try {
      sessionStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      /* private mode — dismissing for this render is still fine */
    }
    setDismissed(true);
  };

  const resend = async () => {
    setBusy(true);
    try {
      const res = await resendVerification();
      setMessage(res.detail);
      setCooldown(res.retry_after_seconds ?? 0);
    } catch {
      setMessage("I couldn't reach the server. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b border-line bg-wait-soft px-4 py-2.5 sm:px-6">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 text-[13.5px] leading-relaxed text-ink-2">
          {message ?? (
            <>
              Confirm <span className="font-semibold text-ink">{user.email}</span> when you get a
              moment — it's how you'd get back in if you forgot your password.
            </>
          )}
        </p>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => void resend()}
            disabled={busy || cooldown > 0}
            className="inline-flex h-11 items-center rounded-input px-3 text-[13.5px] font-semibold text-ink underline underline-offset-2 disabled:no-underline disabled:opacity-55"
          >
            {cooldown > 0 ? `Sent — wait ${cooldown}s` : busy ? 'Sending…' : 'Resend'}
          </button>
          <button
            type="button"
            onClick={dismiss}
            aria-label="Dismiss"
            className="grid h-11 w-11 place-items-center rounded-input text-muted hover:text-ink"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
