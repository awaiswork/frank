// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ResetPassword } from './ResetPassword';

const jsonRes = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function renderAt(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/reset-password${search}`]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/login" element={<p>Sign in page</p>} />
        <Route path="/forgot-password" element={<p>Forgot page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function fill(password: string, confirm = password) {
  const [pw, again] = screen.getAllByDisplayValue('');
  fireEvent.change(pw, { target: { value: password } });
  fireEvent.change(again, { target: { value: confirm } });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

// Vitest runs without globals, so testing-library registers no cleanup itself.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('ResetPassword', () => {
  it('treats a missing token as a dead link without calling the server', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderAt('');
    expect(screen.getByText(/link doesn't work any more/i)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses to submit until the password is long enough', () => {
    vi.stubGlobal('fetch', vi.fn());
    renderAt('?token=abc');
    fill('short');
    expect(screen.getByRole('button', { name: /set my password/i })).toHaveProperty(
      'disabled',
      true,
    );
    expect(screen.getByText(/under 8 characters/i)).toBeTruthy();
  });

  it('refuses to submit while the two fields disagree', () => {
    vi.stubGlobal('fetch', vi.fn());
    renderAt('?token=abc');
    fill('long-enough-password', 'something-else');
    expect(screen.getByText(/don't match/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /set my password/i })).toHaveProperty(
      'disabled',
      true,
    );
  });

  it('confirms success and says other sessions were ended', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonRes(200, { detail: 'ok', retry_after_seconds: null }))),
    );
    renderAt('?token=abc');
    fill('long-enough-password');
    fireEvent.click(screen.getByRole('button', { name: /set my password/i }));

    await waitFor(() => expect(screen.getByText(/signed out everywhere else/i)).toBeTruthy());
    expect(screen.getByRole('button', { name: /sign in/i })).toBeTruthy();
  });

  it('shows the expired-link state when the server rejects the token', async () => {
    // The API answers 400 for expired, already-used and tampered alike; the page
    // must not invent a distinction it was never told.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonRes(400, { detail: 'invalid or expired' }))),
    );
    renderAt('?token=stale');
    fill('long-enough-password');
    fireEvent.click(screen.getByRole('button', { name: /set my password/i }));

    await waitFor(() => expect(screen.getByText(/link doesn't work any more/i)).toBeTruthy());
    expect(screen.getByRole('link', { name: /send me a new one/i })).toBeTruthy();
  });

  it('keeps an unreachable server distinct from a bad token', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    );
    renderAt('?token=abc');
    fill('long-enough-password');
    fireEvent.click(screen.getByRole('button', { name: /set my password/i }));

    await waitFor(() => expect(screen.getByText(/couldn't reach the server/i)).toBeTruthy());
    // Still on the form — the token may be perfectly good.
    expect(screen.getByRole('button', { name: /set my password/i })).toBeTruthy();
    expect(screen.queryByText(/link doesn't work any more/i)).toBeNull();
  });
});
