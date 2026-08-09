/**
 * Tiny typed fetch client. The access token lives in memory only (never in
 * localStorage); the refresh token is an httpOnly cookie the browser sends to
 * /auth/* automatically. On a 401 we transparently try one refresh + retry.
 *
 * Every request carries a deadline, because `fetch` has none of its own. A
 * request to a sleeping free-tier instance — or one issued as a phone's radio
 * wakes and the connection is open but dead — can stay pending indefinitely: it
 * never resolves, never rejects, so no `catch` and no `finally` ever runs. A
 * `finally` cannot save you here; only an abort makes the await settle. Anything
 * gating UI on such a promise waits forever, which is exactly how the app used
 * to get stuck on "Loading…" after a night in a backgrounded tab.
 */

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

/** Normal in-app requests. Generous: the API sleeps and is slow to wake. */
export const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Session restore on boot — the call most likely to meet a cold start, since it
 * waits for Render to spin the instance up *and* for /auth/refresh's user lookup
 * to wake Neon behind it. (/healthz deliberately touches no database, so the
 * platform can call the service live while this is still blocked.) Matches the
 * "up to a minute" the cold-start notice promises.
 */
export const BOOTSTRAP_TIMEOUT_MS = 60_000;

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * Why a call failed, for the callers that must tell the two apart. Only the API
 * answering 401 means the session is over; everything else — 5xx, a timeout, a
 * dead connection — is 'unreachable' and must not be dressed up as being signed
 * out, because a login screen would fail the same way and blame the user for it.
 */
export type FailureReason = 'unauthenticated' | 'unreachable';

export type RefreshResult = { ok: true } | { ok: false; reason: FailureReason };

/** Classify a rejection from `apiFetch`. Anything that isn't the API saying 401. */
export function failureReason(err: unknown): FailureReason {
  return err instanceof ApiError && err.status === 401 ? 'unauthenticated' : 'unreachable';
}

/**
 * Run `work` under a deadline, aborting it if `ms` elapses first.
 *
 * Uses a plain timer rather than `AbortSignal.timeout()` so tests can drive it
 * with fake timers. The deadline spans reading the body too, not just the
 * headers — a server that answers and then stalls mid-body hangs just as hard as
 * one that never answers at all.
 */
async function withDeadline<T>(
  ms: number,
  external: AbortSignal | null | undefined,
  work: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new DOMException(`Timed out after ${ms}ms`, 'TimeoutError')),
    ms,
  );
  const relay = () => controller.abort(external?.reason);
  if (external?.aborted) relay();
  else external?.addEventListener('abort', relay);

  try {
    return await work(controller.signal);
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', relay);
  }
}

function rawFetch(path: string, init: RequestInit, signal: AbortSignal): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set('Content-Type', 'application/json');
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  return fetch(`${API_URL}${path}`, { ...init, headers, credentials: 'include', signal });
}

let onSessionExpired: (() => void) | null = null;

/**
 * Register the app's reaction to "the session is gone".
 *
 * Boot is not the only way a session ends. It can be revoked from another
 * device (sign out everywhere), ended by a password reset, or simply expire
 * while a tab sits open — and all of those first surface as a 401 on some
 * ordinary query, long after the provider finished deciding you were signed in.
 * Without this, the refresh quietly fails, the query shows an error, and the
 * user is left on a screen that no longer works and never says why.
 *
 * Only fired for a genuine "not authenticated". An unreachable server is a
 * different thing and must not throw anyone out to a login form that would fail
 * the same way.
 */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

let inFlightRefresh: Promise<RefreshResult> | null = null;

/**
 * Exchange the refresh cookie for a fresh access token. Never throws; reports
 * why it failed so the caller can route to login or to a retry screen.
 *
 * Single-flight: Home mounts five queries at once and Layout a sixth, so a
 * shared 401 would otherwise fire six simultaneous refreshes at an instance
 * that — by hypothesis — is already struggling to answer one.
 */
export function refreshAccessToken(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<RefreshResult> {
  inFlightRefresh ??= runRefresh(timeoutMs)
    .then((result) => {
      if (!result.ok && result.reason === 'unauthenticated') onSessionExpired?.();
      return result;
    })
    .finally(() => {
      inFlightRefresh = null;
    });
  return inFlightRefresh;
}

async function runRefresh(timeoutMs: number): Promise<RefreshResult> {
  try {
    return await withDeadline(timeoutMs, null, async (signal) => {
      const res = await rawFetch('/auth/refresh', { method: 'POST' }, signal);
      if (!res.ok) {
        setAccessToken(null);
        return {
          ok: false,
          reason: res.status === 401 ? 'unauthenticated' : 'unreachable',
        } as const;
      }
      const data = (await res.json()) as { access_token: string };
      setAccessToken(data.access_token);
      return { ok: true } as const;
    });
  } catch {
    // Timed out, aborted, or the request never got off the ground.
    setAccessToken(null);
    return { ok: false, reason: 'unreachable' };
  }
}

/**
 * Knock on the API until it answers, then resolve. Never rejects.
 *
 * Only needed before a *top-level navigation* to the API — Google sign-in. Every
 * other slow call happens with the app still on screen, where `ProtectedRoute`
 * and `AuthCallback` can say "waking the server up" and be believed. A link to a
 * sleeping instance has no such luxury: the browser leaves the app immediately,
 * paints nothing, and a Render cold start is 30–60 seconds of blank white page
 * on a domain the user has never heard of. That reads as a broken button, not as
 * waiting, and it is why the button appeared not to work at all.
 *
 * `/healthz` is the right door to knock on precisely because it touches no
 * database (CLAUDE.md keeps it that way): it answers as soon as the instance is
 * up, instead of also waiting for Neon to wake behind it.
 *
 * Failure is deliberately not propagated. A ping that times out is no reason to
 * refuse to navigate — the server may answer the navigation anyway, and
 * stranding someone on the sign-in screen is worse than letting them wait on
 * Google's.
 */
export async function warmApi(timeoutMs = BOOTSTRAP_TIMEOUT_MS): Promise<void> {
  try {
    await withDeadline(timeoutMs, null, (signal) =>
      fetch(`${API_URL}/healthz`, { signal, cache: 'no-store' }),
    );
  } catch {
    /* best effort; the caller navigates regardless */
  }
}

async function toError(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') detail = body.detail;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail);
}

export function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  return withDeadline(timeoutMs, init.signal, async (signal) => {
    let res = await rawFetch(path, init, signal);

    // One transparent refresh + retry on an expired access token. Bounded: the
    // refresh calls `rawFetch` directly, so it can never re-enter this function.
    if (res.status === 401 && !path.startsWith('/auth/')) {
      const refreshed = await refreshAccessToken(timeoutMs);
      if (refreshed.ok) res = await rawFetch(path, init, signal);
    }

    if (!res.ok) throw await toError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  });
}

export const json = (body: unknown): string => JSON.stringify(body);
