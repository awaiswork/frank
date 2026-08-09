// @vitest-environment jsdom
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { QuickAdd } from './QuickAdd';

// Accounts the mocked hook hands back. Mutable so a test can say "none yet".
let accounts: { id: string; name: string; archived_at: string | null }[] = [];

// The sheet only needs the shape of these, not a server.
vi.mock('../api/hooks', () => ({
  useCategories: () => ({ data: [{ id: 'c1', name: 'Fun', kind: 'expense', color: null }] }),
  useTransactions: () => ({ data: [] }),
  useCreateTransaction: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteTransaction: () => ({ mutate: vi.fn() }),
  useAccounts: () => ({
    data: { accounts, total_cents: 0, ledger_starts_on: null },
  }),
}));

vi.mock('../auth/useAuth', () => ({ useAuth: () => ({ user: { id: 'u1' } }) }));

beforeAll(() => {
  // jsdom has no matchMedia; the sheet asks it whether the pointer is coarse.
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});

/** Stand-in for the app behind the sheet, so we can watch it go inert. */
function mountAppRoot() {
  const appRoot = document.createElement('div');
  appRoot.id = 'root';
  const trigger = document.createElement('button');
  trigger.textContent = 'Log an expense';
  appRoot.append(trigger);
  document.body.append(appRoot);
  trigger.focus();
  return { appRoot, trigger };
}

// Vitest runs without globals, so testing-library never registers its own
// cleanup — without this, each test's sheet stays on <body> and the next test
// queries the previous one.
afterEach(() => {
  cleanup();
  document.getElementById('root')?.remove();
  accounts = [];
  localStorage.clear();
});

function dialog() {
  return document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]');
}

describe('QuickAdd', () => {
  it('renders onto <body>, not into the tree that mounted it', () => {
    render(<QuickAdd open onClose={() => {}} />);

    // Page roots animate a transform, which makes them the containing block for
    // `position: fixed`. A sheet left inside one centres on that page's column
    // instead of the viewport, so it has to be a child of <body>.
    expect(dialog()?.parentElement).toBe(document.body);
  });

  it('makes the page behind unreachable while it is open', () => {
    const { appRoot } = mountAppRoot();
    const { rerender } = render(<QuickAdd open onClose={() => {}} />);

    expect(appRoot.inert).toBe(true);
    expect(dialog()?.contains(document.activeElement)).toBe(true);

    rerender(<QuickAdd open={false} onClose={() => {}} />);
    expect(appRoot.inert).toBe(false);
  });

  it('hands focus back to whatever opened it', () => {
    const { trigger } = mountAppRoot();
    const { rerender } = render(<QuickAdd open onClose={() => {}} />);
    expect(document.activeElement).not.toBe(trigger);

    rerender(<QuickAdd open={false} onClose={() => {}} />);
    expect(document.activeElement).toBe(trigger);
  });

  it('closes on Escape and releases the scroll lock', () => {
    const onClose = vi.fn();
    const { rerender } = render(<QuickAdd open onClose={onClose} />);
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();

    rerender(<QuickAdd open={false} onClose={onClose} />);
    expect(document.body.style.overflow).toBe('');
  });

  it('mounts blank each time, so a visit never inherits the last one', () => {
    const { rerender } = render(<QuickAdd open onClose={() => {}} />);
    const amount = () => document.querySelector<HTMLInputElement>('input[aria-label="Amount"]');
    fireEvent.change(amount()!, { target: { value: '12,50' } });
    expect(amount()?.value).toBe('12,50');

    rerender(<QuickAdd open={false} onClose={() => {}} />);
    rerender(<QuickAdd open onClose={() => {}} />);
    expect(amount()?.value).toBe('');
  });

  it('shows no account picker for someone who has none', () => {
    // The whole point of nullable account_id: an app with no accounts logs exactly
    // the way it always did.
    render(<QuickAdd open onClose={() => {}} />);
    expect(document.querySelector('[aria-pressed]')).toBeNull();
  });

  it('opens on the account used last on this device, not just the first', () => {
    accounts = [
      { id: 'a1', name: 'Everyday', archived_at: null },
      { id: 'a2', name: 'Savings', archived_at: null },
    ];
    localStorage.setItem('frankly-last-account:u1', 'a2');

    render(<QuickAdd open onClose={() => {}} />);
    const pressed = [...document.querySelectorAll('[aria-pressed="true"]')].map(
      (el) => el.textContent,
    );
    expect(pressed).toEqual(['Savings']);
  });

  it('ignores a remembered account that has since been archived', () => {
    accounts = [{ id: 'a1', name: 'Everyday', archived_at: null }];
    localStorage.setItem('frankly-last-account:u1', 'gone');

    render(<QuickAdd open onClose={() => {}} />);
    const pressed = [...document.querySelectorAll('[aria-pressed="true"]')].map(
      (el) => el.textContent,
    );
    expect(pressed).toEqual(['Everyday']);
  });
});
