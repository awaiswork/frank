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
  /** IANA name. null means never set — the server reads dates as UTC until it is. */
  timezone: string | null;
  monthly_income_cents: number | null;
  /** Verification is a soft gate — false means "show the banner", never "block". */
  email_verified: boolean;
}

/** The shape every non-resource auth endpoint answers with. */
export interface AuthMessage {
  detail: string;
  /** Present on cooldown responses so the UI can count down instead of guessing. */
  retry_after_seconds: number | null;
}

export interface Category {
  id: string;
  name: string;
  kind: Kind;
  color: string | null;
}

export type AccountType = 'current' | 'savings' | 'cash' | 'liability';

export interface Account {
  id: string;
  name: string;
  type: AccountType;
  currency: string;
  opening_balance_cents: number;
  opened_on: string; // YYYY-MM-DD
  archived_at: string | null;
  /** Derived from the ledger on every read, never stored. */
  balance_cents: number;
  entry_count: number;
}

export interface AccountsPayload {
  accounts: Account[];
  total_cents: number;
  /** null until the first account exists. Balances only count entries from here on. */
  ledger_starts_on: string | null;
}

export interface AccountCreate {
  name: string;
  type: AccountType;
  opening_balance_cents?: number;
  opened_on?: string;
}

export interface Transaction {
  id: string;
  kind: Kind;
  /** null means it predates the ledger — counts as spending, never toward a balance. */
  account_id: string | null;
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
  account_id?: string | null;
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
  /** False when there's no stated income and none logged — safe_to_spend_cents
   * is then just negative spend and must not be shown as a verdict. */
  income_known: boolean;
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

/** A draft from POST /nl/parse — not persisted; the user confirms it. */
export interface NlDraft {
  kind: Kind;
  amount_cents: number;
  description: string;
  merchant: string | null;
  occurred_on: string;
  category_id: string | null;
  category_name: string | null;
  confidence: number;
}

// --- Advisor (M4) ---
export type VerdictKind = 'go' | 'wait' | 'skip' | 'your_call';

export interface Evidence {
  label: string;
  value: string;
}

/** The `verdict` SSE event payload from /advisor/ask. */
export interface AdviceVerdict {
  id: string;
  verdict: VerdictKind;
  headline: string;
  evidence: Evidence[];
  reasoning: string;
  disclaimer: string;
}

export interface AdviceHistory {
  id: string;
  question: string;
  amount_cents: number | null;
  verdict: VerdictKind | null;
  reasoning: string;
  evidence: Evidence[];
  user_followed: boolean | null;
  created_at: string;
}

// --- Daily note (the hook) ---
/** 'unknown' = no income on file, so Frankly owes a setup prompt, not a verdict. */
export type DayMood = 'go' | 'wait' | 'over' | 'unknown';

export interface DailyNote {
  date: string; // YYYY-MM-DD
  mood: DayMood;
  headline: string;
  note: string;
  streak: number;
}

// --- Feature flags ---
/** GET /features — which optional features this deployment has switched on.
 * The model-backed ones cost API usage, so they can be turned off server-side. */
export interface Features {
  ai_enabled: boolean;
  nl_capture: boolean;
  advisor: boolean;
  ai_daily_note: boolean;
}
