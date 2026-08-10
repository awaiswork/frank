import { createContext } from 'react';
import type { TransactionKind } from '../api/types';

/**
 * Fields the sheet should open on, when a screen knows better than a blank form.
 *
 * A refund is the case this exists for: you refund *a purchase*, so opening on that
 * purchase's amount, category and account is both less typing and more honest than
 * asking someone to retype what the row already says.
 */
export interface CapturePrefill {
  kind?: TransactionKind;
  amountCents?: number;
  categoryId?: string | null;
  accountId?: string | null;
  description?: string;
}

export interface CaptureContextValue {
  /** Open the quick-add sheet. Callable from any screen under <Layout>. */
  open: (prefill?: CapturePrefill) => void;
}

/**
 * One capture sheet for the whole app.
 *
 * Screens used to mount their own <QuickAdd>, which meant two sheets could be
 * open at once — the page's, plus Layout's from ⌘K (its handler runs before the
 * "is the user typing?" guard). That stacked two backdrops and two
 * `aria-modal` dialogs. Pages ask for the sheet through here instead of
 * mounting one.
 */
export const CaptureContext = createContext<CaptureContextValue | null>(null);
