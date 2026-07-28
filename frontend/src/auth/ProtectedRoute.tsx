import { useEffect, useState } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { Button } from '../components/ui';
import { useAuth } from './useAuth';

/**
 * The API sleeps after 15 idle minutes and takes 30–60s to wake. Past a few
 * seconds a bare spinner reads as "broken" and people reload — so say what is
 * actually happening instead of leaving them to guess.
 */
const WAKING_NOTICE_MS = 3000;

/**
 * True once `active` has held for `ms`. Gated on `active` at the point of use
 * rather than reset on the way out, so the flag is derived and the effect only
 * ever schedules. One consequence, and it's the behaviour we want: after a retry
 * the notice shows straight away — we already know this server is slow to wake,
 * so pretending otherwise for another three seconds would be a step backwards.
 */
function useElapsed(active: boolean, ms: number): boolean {
  const [elapsed, setElapsed] = useState(false);
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => setElapsed(true), ms);
    return () => clearTimeout(timer);
  }, [active, ms]);
  return active && elapsed;
}

export function ProtectedRoute() {
  const { status, retry } = useAuth();
  const waking = useElapsed(status === 'loading', WAKING_NOTICE_MS);

  if (status === 'loading') return <Restoring waking={waking} />;
  if (status === 'unreachable') return <Unreachable onRetry={retry} />;
  if (status === 'anon') return <Navigate to="/login" replace />;
  return <Outlet />;
}

function Restoring({ waking }: { waking: boolean }) {
  return (
    <div className="grid min-h-svh place-items-center px-6 text-center">
      <div className="flex max-w-[34ch] flex-col items-center gap-3">
        <span className="animate-spin-fast inline-block h-[22px] w-[22px] rounded-full border-2 border-line-2 border-t-ink" />
        {waking ? (
          <>
            <p className="text-[15px] font-semibold text-ink">Waking the server up…</p>
            <p className="text-[14px] leading-relaxed text-muted">
              It goes to sleep when nobody's using it. This can take up to a minute.
            </p>
          </>
        ) : (
          <p className="text-[15px] text-muted">Loading…</p>
        )}
      </div>
    </div>
  );
}

/** Not the login screen: we never heard back, so we don't know they're signed out. */
function Unreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="grid min-h-svh place-items-center px-6 text-center">
      <div className="flex max-w-[36ch] flex-col items-center gap-4">
        <div>
          <p className="font-display text-[19px] font-semibold tracking-[-0.01em] text-ink">
            Can't reach the server
          </p>
          <p className="mt-1.5 text-[14.5px] leading-relaxed text-muted">
            It may still be waking up, or the connection dropped. You haven't been signed out.
          </p>
        </div>
        <Button onClick={onRetry}>Try again</Button>
      </div>
    </div>
  );
}
