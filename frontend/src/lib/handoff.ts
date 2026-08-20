/**
 * The secret Google's callback leaves in the URL, and getting rid of it again.
 *
 * It arrives in the *fragment* — `/auth/callback#handoff=…` — rather than the
 * query string, because the fragment is the one part of a URL that is sent to
 * nobody: it reaches no access log and no `Referer` header. It does reach this
 * tab's history, which is why `forgetHandoff` runs the moment the value has been
 * read, and why the API burns it on first use and expires it in two minutes.
 *
 * Read from `window.location` rather than from the router, deliberately. This is
 * about the URL the browser was actually handed on a full page load — the router
 * models that, and in tests models it entirely in memory.
 */

const PARAM = 'handoff';

/** The only path the API redirects to. A fragment anywhere else is not ours. */
const CALLBACK_PATH = '/auth/callback';

/** The handoff this page load is carrying, if it is carrying one. */
export function pendingHandoff(): string | null {
  if (window.location.pathname.replace(/\/$/, '') !== CALLBACK_PATH) return null;
  return new URLSearchParams(window.location.hash.slice(1)).get(PARAM) || null;
}

/** Drop it out of the address bar and out of the history entry behind it. */
export function forgetHandoff(): void {
  // `replaceState`, not `location.hash = ''`: assigning the hash leaves the '#'
  // behind and pushes a *new* history entry, so Back would return to a URL still
  // carrying the secret. This rewrites the entry that already exists.
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
}
