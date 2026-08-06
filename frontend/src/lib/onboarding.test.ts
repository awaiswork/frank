// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { hasOnboarded, markOnboarded } from './onboarding';

afterEach(() => localStorage.clear());

describe('onboarding state', () => {
  it('is remembered for the account that finished it', () => {
    expect(hasOnboarded('user-a')).toBe(false);
    markOnboarded('user-a');
    expect(hasOnboarded('user-a')).toBe(true);
  });

  it('does not leak to another account on the same browser', () => {
    // The bug this replaced: one global `frankly-onboarded` key meant that once
    // anyone finished setup on a machine, every account made there afterwards
    // skipped it — invisibly, with no way back. Google sign-in made a second
    // account a single click, so this stopped being a corner case.
    markOnboarded('user-a');
    expect(hasOnboarded('user-b')).toBe(false);
  });

  it('ignores the retired global key', () => {
    localStorage.setItem('frankly-onboarded', '1');
    expect(hasOnboarded('user-a')).toBe(false);
  });

  it('treats unreadable storage as not-yet-onboarded', () => {
    // Private mode. Showing setup again is the safe way to be wrong; hiding it
    // from someone who has never seen it is not.
    const original = Object.getOwnPropertyDescriptor(Storage.prototype, 'getItem');
    Storage.prototype.getItem = () => {
      throw new Error('denied');
    };
    try {
      expect(hasOnboarded('user-a')).toBe(false);
      expect(() => markOnboarded('user-a')).not.toThrow();
    } finally {
      if (original) Object.defineProperty(Storage.prototype, 'getItem', original);
    }
  });
});
