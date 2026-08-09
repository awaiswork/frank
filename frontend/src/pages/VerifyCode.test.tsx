// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setAccessToken } from '../api/client';
import { AuthProvider } from '../auth/AuthProvider';
import { VerifyCode } from './VerifyCode';

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

function renderAt(state: Record<string, string | number | null> | null) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[{ pathname: '/verify', state }]}>
        <AuthProvider>
          <Routes>
            <Route path="/verify" element={<VerifyCode />} />
            <Route path="/register" element={<p>Register page</p>} />
            <Route path="/forgot-password" element={<p>Forgot page</p>} />
            <Route path="/reset-password" element={<p>Set a new password</p>} />
            <Route path="/" element={<p>App content</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const field = () => screen.getByLabelText('Six-digit code');

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setAccessToken(null);
});

describe('VerifyCode', () => {
  it('sends you back when there is no address to verify against', () => {
    // A refresh or a pasted URL loses the router state. A dead form would be
    // worse than starting over.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonRes(401, {}))),
    );
    renderAt(null);
    expect(screen.getByText('Register page')).toBeTruthy();
  });

  it('keeps the submit button disabled until six digits are entered', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonRes(401, {}))),
    );
    renderAt({ email: 'a@b.co', purpose: 'verify' });

    const submit = screen.getByRole('button', { name: /confirm/i });
    expect(submit).toHaveProperty('disabled', true);
    fireEvent.change(field(), { target: { value: '1234' } });
    expect(submit).toHaveProperty('disabled', true);
    fireEvent.change(field(), { target: { value: '123456' } });
    expect(submit).toHaveProperty('disabled', false);
  });

  it('strips anything that is not a digit', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonRes(401, {}))),
    );
    renderAt({ email: 'a@b.co', purpose: 'verify' });
    fireEvent.change(field(), { target: { value: '12-34 ab56789' } });
    expect((field() as HTMLInputElement).value).toBe('123456');
  });

  it('shows the server message on a wrong code and clears the field', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve(
          String(url).includes('/auth/verify-code')
            ? jsonRes(400, { detail: 'That code is wrong or has expired.' })
            : jsonRes(401, {}),
        ),
      ),
    );
    renderAt({ email: 'a@b.co', purpose: 'verify' });

    fireEvent.change(field(), { target: { value: '000000' } });
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }));

    await waitFor(() => expect(screen.getByText(/wrong or has expired/i)).toBeTruthy());
    // Cleared so the next attempt starts from nothing rather than an edit.
    expect((field() as HTMLInputElement).value).toBe('');
  });

  it('signs you in on the right code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const path = String(url);
        if (path.includes('/auth/verify-code'))
          return Promise.resolve(jsonRes(200, { access_token: 't' }));
        if (path.includes('/me')) return Promise.resolve(jsonRes(200, ME));
        return Promise.resolve(jsonRes(401, {}));
      }),
    );
    renderAt({ email: 'a@b.co', purpose: 'verify' });

    fireEvent.change(field(), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }));

    await waitFor(() => expect(screen.getByText('App content')).toBeTruthy());
  });

  it('carries the reset ticket forward without putting it in the URL', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve(
          String(url).includes('/auth/verify-reset-code')
            ? jsonRes(200, { ticket: 'secret-ticket' })
            : jsonRes(401, {}),
        ),
      ),
    );
    renderAt({ email: 'a@b.co', purpose: 'reset' });

    fireEvent.change(field(), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));

    await waitFor(() => expect(screen.getByText('Set a new password')).toBeTruthy());
    expect(window.location.search).not.toContain('secret-ticket');
  });

  it('counts down after a resend, so the button explains itself', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve(
          String(url).includes('/auth/resend-code')
            ? jsonRes(200, { detail: 'sent', retry_after_seconds: 60 })
            : jsonRes(401, {}),
        ),
      ),
    );
    renderAt({ email: 'a@b.co', purpose: 'verify' });

    fireEvent.click(screen.getByRole('button', { name: /send another code/i }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /send another in/i })).toBeTruthy(),
    );
    expect(screen.getByRole('button', { name: /send another in/i })).toHaveProperty(
      'disabled',
      true,
    );
  });

  describe('not offering a send that would be silently declined', () => {
    // `/auth/resend-code` answers the same whether it sent a code or dropped it
    // on the per-user cooldown — it has to, or the response would confirm which
    // addresses are registered. So the screen used to offer "Send another code"
    // straight after registration, the server declined in silence, and the
    // screen reported success. The arriving page carries the cooldown instead.

    it('starts held down when the previous screen just sent a code', () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(() => Promise.resolve(jsonRes(401, {}))),
      );
      renderAt({ email: 'a@b.co', purpose: 'verify', retryAfter: 60 });

      const button = screen.getByRole('button', { name: /send another in/i });
      expect(button).toHaveProperty('disabled', true);
      expect(screen.queryByRole('button', { name: /send another code/i })).toBeNull();
    });

    it('starts live when nothing was sent', () => {
      // The login route raises a 403 without sending, and the request that
      // should have replaced it can itself be throttled. Nothing is on its way,
      // so the one button that can fix that must not be disabled.
      vi.stubGlobal(
        'fetch',
        vi.fn(() => Promise.resolve(jsonRes(401, {}))),
      );
      renderAt({ email: 'a@b.co', purpose: 'verify', retryAfter: null });

      expect(screen.getByRole('button', { name: /send another code/i })).toHaveProperty(
        'disabled',
        false,
      );
    });

    it('repeats what the server said rather than claiming a send of its own', async () => {
      const neutral = "If that address has an account, I've sent a code to it.";
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) =>
          Promise.resolve(
            String(url).includes('/auth/resend-code')
              ? jsonRes(200, { detail: neutral, retry_after_seconds: 60 })
              : jsonRes(401, {}),
          ),
        ),
      );
      renderAt({ email: 'a@b.co', purpose: 'reset' });

      fireEvent.click(screen.getByRole('button', { name: /send another code/i }));

      await waitFor(() => expect(screen.getByText(neutral)).toBeTruthy());
      // The old copy asserted delivery the client could not know about.
      expect(screen.queryByText(/^Sent\./)).toBeNull();
    });
  });

  it('separates an unreachable server from a rejected code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        String(url).includes('/auth/verify-code')
          ? Promise.reject(new TypeError('Failed to fetch'))
          : Promise.resolve(jsonRes(401, {})),
      ),
    );
    renderAt({ email: 'a@b.co', purpose: 'verify' });

    fireEvent.change(field(), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }));

    await waitFor(() => expect(screen.getByText(/couldn't reach the server/i)).toBeTruthy());
  });
});
