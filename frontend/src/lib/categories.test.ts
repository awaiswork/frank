import { describe, expect, it } from 'vitest';
import type { Category, Kind, Transaction } from '../api/types';
import { rankCategories } from './categories';

const cat = (id: string, name: string, kind: Kind = 'expense'): Category => ({
  id,
  name,
  kind,
  color: null,
});

const tx = (categoryId: string | null, kind: Kind = 'expense'): Transaction => ({
  id: `t-${Math.random()}`,
  kind,
  account_id: null,
  counter_account_id: null,
  recurring_template_id: null,
  amount_cents: 100,
  description: 'x',
  merchant: null,
  occurred_on: '2026-07-27',
  category_id: categoryId,
  source: 'manual',
  created_at: '2026-07-27T00:00:00Z',
});

const CATEGORIES = [
  cat('bills', 'Bills'),
  cat('eating', 'Eating out'),
  cat('groceries', 'Groceries'),
  cat('salary', 'Income', 'income'),
];

describe('rankCategories', () => {
  it('puts the most-used category first', () => {
    const used = [tx('groceries'), tx('groceries'), tx('eating')];
    expect(rankCategories(CATEGORIES, used, 'expense').map((c) => c.name)).toEqual([
      'Groceries',
      'Eating out',
      'Bills',
    ]);
  });

  it('keeps never-used categories available, after the used ones', () => {
    const ranked = rankCategories(CATEGORIES, [tx('bills')], 'expense');
    expect(ranked.map((c) => c.name)).toEqual(['Bills', 'Eating out', 'Groceries']);
  });

  it('breaks ties by the original order rather than shuffling the chips', () => {
    // Same usage count everywhere -> the layout must stay stable between renders.
    const ranked = rankCategories(CATEGORIES, [], 'expense');
    expect(ranked.map((c) => c.name)).toEqual(['Bills', 'Eating out', 'Groceries']);
  });

  it('only offers categories matching the kind being logged', () => {
    expect(rankCategories(CATEGORIES, [], 'income').map((c) => c.name)).toEqual(['Income']);
  });

  it('ignores usage from the other kind', () => {
    // Income logged against a category must not promote it in the expense list.
    const ranked = rankCategories(CATEGORIES, [tx('groceries', 'income')], 'expense');
    expect(ranked.map((c) => c.name)).toEqual(['Bills', 'Eating out', 'Groceries']);
  });

  it('ignores uncategorised transactions', () => {
    expect(rankCategories(CATEGORIES, [tx(null), tx(null)], 'expense')).toHaveLength(3);
  });
});
