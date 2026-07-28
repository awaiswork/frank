import { createContext } from 'react';

export interface CaptureContextValue {
  /** Open the quick-add sheet. Callable from any screen under <Layout>. */
  open: () => void;
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
