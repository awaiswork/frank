import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { googleSignInUrl } from '../api/auth';
import { warmApi } from '../api/client';

/**
 * "Continue with Google", for both the sign-in and sign-up screens.
 *
 * One component because the two pages must not drift: this is the only route
 * into the app that works for someone whose address Resend cannot reach, so a
 * missing button on the sign-up screen means a stranger has no way to create an
 * account at all.
 *
 * An anchor, not a button with `fetch`. The flow is a chain of top-level
 * redirects through Google's consent screen and back, which XHR cannot follow.
 *
 * The click is intercepted anyway, for one reason: the destination is the API,
 * and on the free tier the API sleeps. Following the link straight to a cold
 * instance hands the browser a blank page on `*.onrender.com` for 30–60 seconds
 * with nothing on it to explain the wait — the one slow path in this app that
 * had no cold-start notice, and indistinguishable from a button that does
 * nothing. So we wake the server *here*, where the screen still belongs to us
 * and can say what is happening, and navigate once it answers.
 *
 * The `href` stays real and correct: modified clicks (new tab, new window) are
 * left to the browser, and with JavaScript broken the link still works — badly,
 * exactly as it did before, rather than not at all.
 */
export function GoogleButton({ label }: { label: string }) {
  const [waking, setWaking] = useState(false);
  const href = googleSignInUrl();
  // Guards a navigation firing after this screen is gone: the wake can outlive
  // the component, and a redirect landing on whatever the user opened instead
  // would be worse than the wait it was meant to cover.
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  async function onClick(event: MouseEvent<HTMLAnchorElement>) {
    // Leave the browser the clicks it owns — new tab, new window, download.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (waking) return;
    setWaking(true);
    await warmApi();
    if (alive.current) window.location.assign(href);
  }

  return (
    <>
      <div className="mt-5 flex items-center gap-3" aria-hidden="true">
        <span className="h-px flex-1 bg-line" />
        <span className="text-[12px] text-muted">or</span>
        <span className="h-px flex-1 bg-line" />
      </div>
      <a
        href={href}
        onClick={onClick}
        aria-busy={waking}
        className={`mt-4 flex h-11 w-full items-center justify-center gap-2.5 rounded-input border border-line-2 bg-surface text-[14.5px] font-semibold ${
          waking ? 'text-muted' : 'text-ink-2 hover:text-ink'
        }`}
      >
        {waking ? (
          <span className="animate-spin-fast inline-block h-[15px] w-[15px] rounded-full border-2 border-line-2 border-t-ink" />
        ) : (
          <GoogleMark />
        )}
        {waking ? 'Taking you to Google…' : label}
      </a>
      {/* Same promise the rest of the app makes about a cold start, and for the
          same reason: a wait nobody explained is the one people read as broken. */}
      {waking && (
        <p role="status" className="mt-2 text-center text-[12.5px] leading-relaxed text-muted">
          Waking the server up — this can take up to a minute.
        </p>
      )}
    </>
  );
}

/** Google's mark, inline so the page fetches nothing external. */
function GoogleMark() {
  return (
    <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M45 24c0-1.6-.1-2.7-.4-4H24v7.5h12c-.2 2-1.5 5-4.4 7l6.7 5.2C42.2 36 45 30.6 45 24z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.9 0 10.9-2 14.5-5.3l-6.9-5.4c-1.9 1.3-4.4 2.2-7.6 2.2-5.8 0-10.7-3.8-12.5-9.1l-7.1 5.5C8 41.1 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.5 28.4c-.5-1.4-.8-2.9-.8-4.4s.3-3 .7-4.4l-7-5.5C2.9 17 2 20.4 2 24s.9 7 2.4 9.9l7.1-5.5z"
      />
      <path
        fill="#EA4335"
        d="M24 10.7c3.3 0 6.1 1.1 8.4 3.3l6.1-6.1C34.9 4.5 29.9 2 24 2 15.4 2 8 6.9 4.4 14.1l7 5.5c1.8-5.3 6.7-8.9 12.6-8.9z"
      />
    </svg>
  );
}
