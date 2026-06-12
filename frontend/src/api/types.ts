/** Hand-written types mirroring the FastAPI schemas (technical-plan.md §8). */

export type Kind = 'expense' | 'income';

export interface TokenOut {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  currency: string;
  monthly_income_cents: number | null;
}

export interface Category {
  id: string;
  name: string;
  kind: Kind;
  color: string | null;
}

export interface Transaction {
  id: string;
  kind: Kind;
  amount_cents: number;
  description: string;
  merchant: string | null;
  occurred_on: string; // YYYY-MM-DD
  category_id: string | null;
  source: string;
  created_at: string;
}

export interface TransactionCreate {
  kind?: Kind;
  amount_cents: number;
  description: string;
  merchant?: string | null;
  occurred_on: string;
  category_id?: string | null;
}

export interface BudgetActual {
  category_id: string;
  category_name: string;
  color: string | null;
  limit_cents: number;
  spent_cents: number;
  spent_fraction: number;
  elapsed_fraction: number;
  on_track: boolean;
}

export interface Goal {
  id: string;
  name: string;
  target_cents: number;
  due_date: string | null;
  archived_at: string | null;
  contributed_cents: number;
  progress_fraction: number;
}

export interface SafeToSpend {
  income_cents: number;
  spent_cents: number;
  remaining_budgets_cents: number;
  goal_contributions_cents: number;
  safe_to_spend_cents: number;
}

export interface CategorySpend {
  category_id: string | null;
  category_name: string | null;
  color: string | null;
  spent_cents: number;
}

export interface BurnRate {
  trailing_days: number;
  total_spent_cents: number;
  daily_burn_cents: number;
}

export interface CategoryMoM {
  category_id: string | null;
  category_name: string | null;
  color: string | null;
  this_month_cents: number;
  prev_month_cents: number;
  delta_cents: number;
}

export interface InsightsSummary {
  month: string;
  safe_to_spend: SafeToSpend;
  spend_by_category: CategorySpend[];
  daily_burn: BurnRate;
  month_over_month: CategoryMoM[];
}
