// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BOOTSTRAP_TIMEOUT_MS, setAccessToken } from '../api/client';
import { AuthProvider } from './AuthProvider';
import { ProtectedRoute } from './ProtectedRoute';

/**
 * The bug these cover: a startup request that never settles. It isn't a rejection
 * a `catch` can see and isn't a failure a `finally` can clean up after — the
 * promise simply never completes, so the app sat on "Loading…" forever. Hence
 * `hangs()`, which models a real stalled connection: pending until aborted.
 */
function hangs() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason));
      }),
  );
}

const jsonRes = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const TOKEN = { access_token: 'fresh-token' };
const ME = { id: 'u1', email: 'a@b.c', currency: 'EUR', monthly_income_cents: 250_000 };

/** Answers /auth/refresh with `refresh`, and /me with a valid user. */
function responds(refresh: () => Response) {
  return vi.fn((url: string) =>
    Promise.resolve(String(url).includes('/auth/refresh') ? refresh() : jsonRes(200, ME)),
  );
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<p>Sign in</p>} />
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<p>Safe to spend</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Let queued promise callbacks run without moving the clock. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setAccessToken(null);
});

// Vitest runs without globals, so testing-library registers no cleanup of its
// own. Draining the timers first settles any request still in flight, so a
// pending refresh can't leak into the next test through the single-flight cache.
afterEach(async () => {
  await advance(BOOTSTRAP_TIMEOUT_MS + 1000);
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('session restore on boot', () => {
  it('resolves to an error screen when the request never comes back', async () => {
    vi.stubGlobal('fetch', hangs());
    renderApp();
    await settle();

    expect(screen.getByText('Loading…')).toBeTruthy();

    // The regression: before the deadline existed, this stayed on "Loading…"
    // for as long as the tab was open.
    await advance(BOOTSTRAP_TIMEOUT_MS + 1);
    expect(screen.getByText("Can't reach the server")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('explains the cold start once the wait stops looking normal', async () => {
    vi.stubGlobal('fetch', hangs());
    renderApp();
    await settle();

    expect(screen.queryByText('Waking the server up…')).toBeNull();

    await advance(3000);
    expect(screen.getByText('Waking the server up…')).toBeTruthy();
  });

  it('sends a 401 to the login screen', async () => {
    vi.stubGlobal(
      'fetch',
      responds(() => jsonRes(401, { detail: 'Missing refresh token' })),
    );
    renderApp();
    await settle();

    expect(screen.getByText('Sign in')).toBeTruthy();
  });

  it('keeps a 5xx away from the login screen', async () => {
    vi.stubGlobal(
      'fetch',
      responds(() => jsonRes(503, { detail: 'no' })),
    );
    renderApp();
    await settle();

    // Being unable to reach the API is not the same as being signed out, and
    // login would fail identically — so this must not route there.
    expect(screen.queryByText('Sign in')).toBeNull();
    expect(screen.getByText("Can't reach the server")).toBeTruthy();
  });

  it('treats a network error as unreachable, not as signed out', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    );
    renderApp();
    await settle();

    expect(screen.queryByText('Sign in')).toBeNull();
    expect(screen.getByText("Can't reach the server")).toBeTruthy();
  });

  it('lets the retry button recover once the server is awake', async () => {
    let awake = false;
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (!awake) return Promise.resolve(jsonRes(503, { detail: 'waking' }));
        return Promise.resolve(
          String(url).includes('/auth/refresh') ? jsonRes(200, TOKEN) : jsonRes(200, ME),
        );
      }),
    );
    renderApp();
    await settle();
    expect(screen.getByText("Can't reach the server")).toBeTruthy();

    awake = true;
    await act(async () => {
      screen.getByRole('button', { name: 'Try again' }).click();
    });
    await settle();

    expect(screen.getByText('Safe to spend')).toBeTruthy();
  });

  it('reaches the app when the session restores', async () => {
    vi.stubGlobal(
      'fetch',
      responds(() => jsonRes(200, TOKEN)),
    );
    renderApp();
    await settle();

    expect(screen.getByText('Safe to spend')).toBeTruthy();
  });
});
