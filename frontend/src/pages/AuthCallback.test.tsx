// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BOOTSTRAP_TIMEOUT_MS, setAccessToken } from '../api/client';
import { AuthProvider } from '../auth/AuthProvider';
import { ProtectedRoute } from '../auth/ProtectedRoute';
import { AuthCallback } from './AuthCallback';

/**
 * The bug these cover: Google sign-in worked on a laptop and failed on every
 * phone. The app and the API are on different sites, so the refresh cookie the
 * callback sets is a third-party cookie — and Safari, which is every browser on
 * iOS, does not send those. This page therefore asked `/auth/refresh` who it was,
 * got a 401 and sent the user back to the login screen it had just come from.
 *
 * `refresh: () => unauthorized` below *is* that browser: every test with it is a
 * phone. The handoff in the URL fragment is the half of the handover that a
 * cookie policy cannot touch.
 */

const jsonRes = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const ME = { id: 'u1', email: 'a@b.c', currency: 'EUR', monthly_income_cents: 250_000 };
const TOKEN = { access_token: 'from-the-handoff' };

const unauthorized = () => jsonRes(401, { detail: 'Invalid refresh token' });

/** Records what was called, so "never asked for the cookie" is assertable. */
function stubApi(answers: { handoff?: () => Response; refresh?: () => Response }) {
  const calls: string[] = [];
  const fetchMock = vi.fn((url: string) => {
    const path = String(url);
    calls.push(path);
    if (path.includes('/auth/google/handoff')) {
      return Promise.resolve((answers.handoff ?? (() => jsonRes(200, TOKEN)))());
    }
    if (path.includes('/auth/refresh')) {
      return Promise.resolve((answers.refresh ?? unauthorized)());
    }
    return Promise.resolve(jsonRes(200, ME));
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

/** Land on the callback the way the API's redirect does. */
function landOn(url: string) {
  window.history.replaceState(null, '', url);
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/auth/callback']}>
        <AuthProvider>
          <Routes>
            <Route path="/auth/callback" element={<AuthCallback />} />
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

async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  setAccessToken(null);
  landOn('/auth/callback#handoff=one-time-secret');
});

// Vitest runs without globals, so testing-library registers no cleanup of its own.
// Draining the timers first settles anything still in flight, so a pending refresh
// can't leak into the next test through the single-flight cache.
afterEach(async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(BOOTSTRAP_TIMEOUT_MS + 1000);
  });
  cleanup();
  landOn('/');
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('finishing a Google sign-in', () => {
  it('signs in from the handoff on a browser that dropped the cookie', async () => {
    const calls = stubApi({ refresh: unauthorized });
    renderApp();
    await settle();

    expect(screen.getByText('Safe to spend')).toBeTruthy();
    expect(calls.some((c) => c.includes('/auth/google/handoff'))).toBe(true);
  });

  it('does not ask for the cookie it is working around', async () => {
    // Not just wasteful: that request answers 401 on the browsers this exists
    // for, and its answer would set 'anon' and bounce a good sign-in to login.
    const calls = stubApi({ refresh: unauthorized });
    renderApp();
    await settle();

    expect(calls.some((c) => c.includes('/auth/refresh'))).toBe(false);
  });

  it('takes the secret out of the URL', async () => {
    stubApi({});
    renderApp();
    await settle();

    // What stays in the address bar stays in this tab's history.
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain('one-time-secret');
  });

  it('spends the handoff exactly once', async () => {
    // It is single-use server-side, so a second attempt is a failed sign-in.
    const calls = stubApi({});
    renderApp();
    await settle();

    expect(calls.filter((c) => c.includes('/auth/google/handoff'))).toHaveLength(1);
  });

  it('falls back to the cookie when there is no handoff to spend', async () => {
    // An older callback, or a fragment that didn't survive the trip.
    landOn('/auth/callback');
    const calls = stubApi({ refresh: () => jsonRes(200, TOKEN) });
    renderApp();
    await settle();

    expect(screen.getByText('Safe to spend')).toBeTruthy();
    expect(calls.some((c) => c.includes('/auth/refresh'))).toBe(true);
  });

  it('falls back to the cookie when the handoff is refused', async () => {
    // Expired or already spent — a reload of this page does exactly that. On a
    // browser that keeps the cookie there is still a real session to restore.
    const calls = stubApi({
      handoff: () => jsonRes(400, { detail: 'That sign-in has expired. Try again.' }),
      refresh: () => jsonRes(200, TOKEN),
    });
    renderApp();
    await settle();

    expect(screen.getByText('Safe to spend')).toBeTruthy();
    expect(calls.some((c) => c.includes('/auth/refresh'))).toBe(true);
  });

  it('sends the user to login when neither half of the handover works', async () => {
    stubApi({ handoff: () => jsonRes(400, { detail: 'gone' }), refresh: unauthorized });
    renderApp();
    await settle();

    expect(screen.getByText('Sign in')).toBeTruthy();
  });

  it('says it is signing you in while it waits', async () => {
    stubApi({});
    renderApp();

    expect(screen.getByText('Signing you in…')).toBeTruthy();
  });
});
