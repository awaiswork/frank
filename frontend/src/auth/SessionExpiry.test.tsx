// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, setAccessToken } from '../api/client';
import { AuthProvider } from './AuthProvider';
import { ProtectedRoute } from './ProtectedRoute';
import { useAuth } from './useAuth';

const jsonRes = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const ME = {
  id: 'u1',
  email: 'a@b.co',
  currency: 'EUR',
  monthly_income_cents: 250000,
  email_verified: true,
};

/** Stands in for the login screen, and reports whether it was told why. */
function LoginStub() {
  const { sessionExpired } = useAuth();
  return <p>{sessionExpired ? 'Signed out: session ended' : 'Sign in'}</p>;
}

function renderApp() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginStub />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<p>App content</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe('a session that ends while the app is open', () => {
  it('routes to login and says why, instead of leaving a broken screen', async () => {
    // Boot succeeds, then the session dies — signed out from another device, or
    // ended by a password reset. Nothing re-runs the bootstrap effect, so this
    // has to reach the provider through the failed refresh itself.
    let alive = true;
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const path = String(url);
        if (path.includes('/auth/refresh')) {
          return Promise.resolve(
            alive ? jsonRes(200, { access_token: 't' }) : jsonRes(401, { detail: 'no' }),
          );
        }
        if (path.includes('/me')) return Promise.resolve(jsonRes(200, ME));
        return Promise.resolve(alive ? jsonRes(200, []) : jsonRes(401, { detail: 'no' }));
      }),
    );

    renderApp();
    await waitFor(() => expect(screen.getByText('App content')).toBeTruthy());

    alive = false;
    await expect(apiFetch('/transactions')).rejects.toThrow();

    await waitFor(() => expect(screen.getByText('Signed out: session ended')).toBeTruthy());
  });

  it('does not throw anyone out when the server is merely unreachable', async () => {
    // The distinction the whole design turns on: 401 means signed out, anything
    // else means we don't know — and a login form would fail identically.
    let reachable = true;
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const path = String(url);
        if (!reachable) return Promise.reject(new TypeError('Failed to fetch'));
        if (path.includes('/auth/refresh'))
          return Promise.resolve(jsonRes(200, { access_token: 't' }));
        if (path.includes('/me')) return Promise.resolve(jsonRes(200, ME));
        return Promise.resolve(jsonRes(200, []));
      }),
    );

    renderApp();
    await waitFor(() => expect(screen.getByText('App content')).toBeTruthy());

    reachable = false;
    await expect(apiFetch('/transactions')).rejects.toThrow();

    // Still in the app. A dropped connection is not a sign-out.
    expect(screen.getByText('App content')).toBeTruthy();
  });
});
