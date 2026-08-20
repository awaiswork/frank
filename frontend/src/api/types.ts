/** Hand-written types mirroring the FastAPI schemas (technical-plan.md §8). */

/** A category is only ever one of these two, and its own DB CHECK says so. */
export type Kind = 'expense' | 'income';

/** What a transaction can be. Wider than Kind: money can move between your own
 *  accounts, come back from a returned purchase, or be corrected against a real
 *  balance — none of which is spending or income. */
export type TransactionKind = Kind | 'transfer' | 'refund' | 'adjustment_up' | 'adjustment_down';

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

/** `person` is someone you have lent to or borrowed from. One type rather than a
 *  receivable/payable pair: the direction is the sign of the balance, so a person you
 *  have both lent to and borrowed from stays one relationship with one number. */
export type AccountType = 'current' | 'savings' | 'cash' | 'liability' | 'person';

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

export interface LendPayload {
  person: string;
  amount_cents: number;
  account_id: string;
  /** True when they are handing money to you, i.e. you are borrowing. */
  borrowing?: boolean;
  description?: string;
}

export interface AccountCreate {
  name: string;
  type: AccountType;
  opening_balance_cents?: number;
  opened_on?: string;
}

export interface Transaction {
  id: string;
  kind: TransactionKind;
  /** null means it predates the ledger — counts as spending, never toward a balance. */
  account_id: string | null;
  /** The far side of a transfer; null for everything else. */
  counter_account_id: string | null;
  /** Set when a recurring template generated this row; null once the template is gone. */
  recurring_template_id: string | null;
  /** What it was, in the currency it happened in. */
  amount_cents: number;
  currency: string;
  /** The same money in your own currency, frozen when it was recorded. */
  base_amount_cents: number;
  description: string;
  merchant: string | null;
  occurred_on: string; // YYYY-MM-DD
  category_id: string | null;
  source: string;
  created_at: string;
}

export interface TransactionCreate {
  kind?: TransactionKind;
  /** Omit for your own currency. With a foreign one, `base_amount_cents` is what a
   *  statement says actually left the account — better evidence than any rate. */
  currency?: string;
  base_amount_cents?: number;
  account_id?: string | null;
  counter_account_id?: string | null;
  amount_cents: number;
  description: string;
  merchant?: string | null;
  occurred_on: string;
  category_id?: string | null;
}

export interface Notifications {
  weekly_digest: boolean;
  /** 0 = Monday, matching Python's `date.weekday()` and the server's CHECK. */
  send_weekday: number;
  /** 0–23, in the reader's own time zone. Hours only: the cron runs hourly. */
  send_hour: number;
}

export type AssetGroup = 'physical' | 'investment';

export interface Asset {
  id: string;
  name: string;
  group: AssetGroup;
  archived_at: string | null;
  /** The latest stated value. null before anything has been said. */
  value_cents: number | null;
  last_valued_on: string | null;
  days_since_valued: number | null;
}

export interface NetWorthPoint {
  on: string;
  accounts_cents: number;
  assets_cents: number;
  total_cents: number;
}

export interface NetWorth {
  points: NetWorthPoint[];
  /** Earliest date the line is comparable. Before it, something now on file wasn't
   *  known yet — a rise there is Frankly learning, not the user gaining. */
  complete_from: string | null;
}

export type Cadence = 'weekly' | 'monthly' | 'yearly';

export interface Recurring {
  id: string;
  name: string;
  kind: Kind;
  amount_cents: number;
  cadence: Cadence;
  start_on: string;
  end_on: string | null;
  category_id: string | null;
  account_id: string | null;
  archived_at: string | null;
  /** Derived from the schedule, so it can never disagree with it. Null once ended. */
  next_on: string | null;
}

export interface RecurringCreate {
  name: string;
  kind?: Kind;
  amount_cents: number;
  cadence?: Cadence;
  start_on?: string;
  end_on?: string | null;
  category_id?: string | null;
  account_id?: string | null;
}

export interface Upcoming {
  template_id: string;
  name: string;
  kind: Kind;
  amount_cents: number;
  occurs_on: string;
  category_id: string | null;
  account_id: string | null;
  skipped: boolean;
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
  /** Recurring expenses still due this month — why the figure above moved. */
  upcoming_cents: number;
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
