// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GoogleButton } from './GoogleButton';

/**
 * The bug these cover: clicking "Continue with Google" navigated the browser
 * straight at the API, which on the free tier is usually asleep. The app was off
 * screen before anything could say so, leaving a blank page on a stranger's
 * domain for the 30–60 seconds of a Render cold start — a wait indistinguishable
 * from a button that simply does nothing, which is how people reported it.
 *
 * So the click must warm the server *first*, while this screen can still explain
 * itself, and navigate only once the server answers.
 */

const API = 'http://localhost:8000';

/** A ping that stays pending until we let it finish — a cold start, modelled. */
function pending() {
  let release!: () => void;
  const done = new Promise<void>((resolve) => {
    release = resolve;
  });
  const fetchMock = vi.fn(() => done.then(() => new Response(null, { status: 200 })));
  return { fetchMock, release };
}

let assign: ReturnType<typeof vi.fn>;

beforeEach(() => {
  assign = vi.fn();
  // jsdom refuses real navigation, so the one call we care about is stubbed.
  Object.defineProperty(window, 'location', {
    value: { ...window.location, assign },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('GoogleButton', () => {
  it('keeps a real href, so the browser still owns new-tab clicks', () => {
    render(<GoogleButton label="Sign up with Google" />);
    expect(screen.getByRole('link')).toHaveProperty('href', `${API}/auth/google/start`);
  });

  it('says it is waking the server instead of leaving a blank page', async () => {
    const { fetchMock, release } = pending();
    vi.stubGlobal('fetch', fetchMock);

    render(<GoogleButton label="Sign up with Google" />);
    await act(async () => {
      screen.getByRole('link').click();
    });

    // Still here, still explaining itself — and pointedly not navigated yet.
    expect(screen.getByRole('status').textContent).toContain('Waking the server up');
    expect(screen.getByRole('link').textContent).toContain('Taking you to Google');
    expect(assign).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(`${API}/healthz`, expect.anything());

    await act(async () => {
      release();
    });
    expect(assign).toHaveBeenCalledWith(`${API}/auth/google/start`);
  });

  it('navigates anyway when the ping fails, rather than stranding the user', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

    render(<GoogleButton label="Continue with Google" />);
    await act(async () => {
      screen.getByRole('link').click();
    });

    expect(assign).toHaveBeenCalledWith(`${API}/auth/google/start`);
  });
});
