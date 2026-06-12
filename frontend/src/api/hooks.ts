/** TanStack Query hooks — one place per resource (technical-plan.md §9). */

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { apiFetch, json } from './client';
import type {
  BudgetActual,
  Category,
  Goal,
  InsightsSummary,
  Transaction,
  TransactionCreate,
} from './types';

const qs = (params: Record<string, string | undefined>): string => {
  const entries = Object.entries(params).filter(([, v]) => v != null && v !== '');
  return entries.length ? `?${new URLSearchParams(entries as [string, string][])}` : '';
};

// Money writes ripple into the budget + insights aggregates (the "64% -> 71%"
// moment), so invalidate them together after any transaction change.
function invalidateMoney(client: QueryClient): void {
  void client.invalidateQueries({ queryKey: ['transactions'] });
  void client.invalidateQueries({ queryKey: ['budgets'] });
  void client.invalidateQueries({ queryKey: ['insights'] });
}

export function useCategories() {
  return useQuery({
    queryKey: ['categories'],
    queryFn: () => apiFetch<Category[]>('/categories'),
    staleTime: 5 * 60 * 1000,
  });
}

export interface TransactionFilters {
  month?: string;
  categoryId?: string;
  q?: string;
}

export function useTransactions(filters: TransactionFilters) {
  return useQuery({
    queryKey: ['transactions', filters],
    queryFn: () =>
      apiFetch<Transaction[]>(
        `/transactions${qs({ month: filters.month, category_id: filters.categoryId, q: filters.q })}`,
      ),
  });
}

export function useCreateTransaction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: TransactionCreate) =>
      apiFetch<Transaction>('/transactions', { method: 'POST', body: json(body) }),
    onSuccess: () => invalidateMoney(client),
  });
}

export function useDeleteTransaction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/transactions/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidateMoney(client),
  });
}

export function useBudgets(month: string) {
  return useQuery({
    queryKey: ['budgets', month],
    queryFn: () => apiFetch<BudgetActual[]>(`/budgets${qs({ month })}`),
  });
}

export function useUpsertBudget(month: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ categoryId, limitCents }: { categoryId: string; limitCents: number }) =>
      apiFetch<BudgetActual>(`/budgets/${categoryId}${qs({ month })}`, {
        method: 'PUT',
        body: json({ limit_cents: limitCents }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['budgets', month] });
      void client.invalidateQueries({ queryKey: ['insights'] });
    },
  });
}

export function useInsights(month: string) {
  return useQuery({
    queryKey: ['insights', month],
    queryFn: () => apiFetch<InsightsSummary>(`/insights/summary${qs({ month })}`),
  });
}

export function useGoals(includeArchived = false) {
  return useQuery({
    queryKey: ['goals', includeArchived],
    queryFn: () =>
      apiFetch<Goal[]>(`/goals${qs({ include_archived: includeArchived ? 'true' : undefined })}`),
  });
}

export function useCreateGoal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; target_cents: number; due_date?: string | null }) =>
      apiFetch<Goal>('/goals', { method: 'POST', body: json(body) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['goals'] }),
  });
}

export function useUpdateGoal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; archived?: boolean; name?: string }) =>
      apiFetch<Goal>(`/goals/${id}`, { method: 'PATCH', body: json(body) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['goals'] }),
  });
}

export function useContribute() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, amountCents }: { id: string; amountCents: number }) =>
      apiFetch<unknown>(`/goals/${id}/contributions`, {
        method: 'POST',
        body: json({ amount_cents: amountCents }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['goals'] });
      void client.invalidateQueries({ queryKey: ['insights'] });
    },
  });
}
