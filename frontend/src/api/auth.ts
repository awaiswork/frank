/**
 * The unauthenticated auth calls: reset, verification, and signing out.
 *
 * Separate from `hooks.ts` because none of these are cached resources — they are
 * one-shot commands, mostly made from pages that no query client is watching.
 */

import { apiFetch, json } from './client';
import type { AuthMessage } from './types';

export function forgotPassword(email: string): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/forgot-password', {
    method: 'POST',
    body: json({ email }),
  });
}

export function resetPassword(token: string, password: string): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/reset-password', {
    method: 'POST',
    body: json({ token, password }),
  });
}

export function verifyEmail(token: string): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/verify-email', {
    method: 'POST',
    body: json({ token }),
  });
}

export function resendVerification(): Promise<AuthMessage> {
  return apiFetch<AuthMessage>('/auth/resend-verification', { method: 'POST' });
}

/**
 * Revoke this session server-side.
 *
 * Not optional, and not best-effort in spirit: the refresh cookie is httpOnly
 * and scoped to /auth, so the browser cannot drop it on its own. Before this
 * endpoint existed, signing out cleared some React state and left a credential
 * in the jar that was still good for thirty days — a reload signed you back in.
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
