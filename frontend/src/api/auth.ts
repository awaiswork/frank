/**
 * The auth calls that aren't cached resources — one-shot commands, mostly made
 * from pages no query client is watching.
 */

import { apiFetch, json } from './client';
import type { AuthMessage, TokenOut } from './types';

/** What a code proves, and therefore which code was sent. */
export type CodePurpose = 'verify' | 'reset';

/**
 * Create the account. Deliberately returns no token — the address has to be
 * proven first, and until then there is nothing to hold.
 */
export function registerAccount(email: string, password: string): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/register', {
    method: 'POST',
    body: json({ email, password }),
  });
}

/** Redeem a signup code. Success is the moment a session begins. */
export function verifyCode(email: string, code: string): Promise<TokenOut> {
  return apiFetch<TokenOut>('/auth/verify-code', {
    method: 'POST',
    body: json({ email, code }),
  });
}

/**
 * Ask for another code.
 *
 * Answers identically for an address that exists and one that doesn't, so the
 * caller cannot learn anything from it and must not try — show the same
 * confirmation either way.
 */
export function resendCode(email: string, purpose: CodePurpose): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/resend-code', {
    method: 'POST',
    body: json({ email, purpose }),
  });
}

export function forgotPassword(email: string): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/forgot-password', {
    method: 'POST',
    body: json({ email }),
  });
}

/** Exchange a reset code for a ticket — step one of two. */
export function verifyResetCode(email: string, code: string): Promise<{ ticket: string }> {
  return apiFetch<{ ticket: string }>('/auth/verify-reset-code', {
    method: 'POST',
    body: json({ email, code }),
  });
}

/** Step two. Does not sign anyone in: reading the inbox isn't proof of identity. */
export function resetPassword(ticket: string, password: string): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/reset-password', {
    method: 'POST',
    body: json({ ticket, password }),
  });
}

/**
 * Revoke this session server-side.
 *
 * The refresh cookie is httpOnly and scoped to /auth, so the browser cannot drop
 * it on its own. Before this endpoint existed, signing out cleared some React
 * state and left a credential in the jar that a reload would happily reuse.
 *
 * Errors are swallowed because the local sign-out has to happen regardless. If
 * the server is unreachable the session outlives the click, which is a smaller
 * problem than a sign-out button that refuses to work offline.
 */
export async function logoutSession(): Promise<void> {
  try {
    await apiFetch<AuthMessage>('/auth/logout', { method: 'POST' });
  } catch {
    /* local sign-out proceeds either way */
  }
}

export async function logoutEverywhere(): Promise<void> {
  await apiFetch<AuthMessage>('/auth/logout-all', { method: 'POST' });
}

/**
 * Where the browser goes to start Google sign-in.
 *
 * A full navigation, not fetch: the flow is a chain of redirects through
 * Google's consent screen and back, which XHR cannot follow. Built from
 * `VITE_API_URL` rather than hardcoded — that value is baked in at build time
 * and changing it needs a redeploy, never a literal here.
 */
export function googleSignInUrl(): string {
  const base = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
  return `${base}/auth/google/start`;
}
