import { useEffect, useRef } from 'react';

/**
 * The chrome every sheet needs: hold the page still behind it, close on Escape,
 * keep focus inside, and hand focus back on the way out.
 *
 * `aria-modal="true"` is a claim that the rest of the page is unavailable, and
 * until the surrounding content is inert the claim is false — Tab walks straight
 * out of the sheet and into the page underneath it. Marking every other child of
 * <body> inert makes it true, which works precisely because overlays are
 * portalled to <body> and so sit as siblings of the app root.
 *
 * Returns a ref for the overlay element. Attach it to the outermost node.
 */
export function useModal(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);

  // Callers pass a fresh arrow function on every render. The effect below must
  // run exactly once per open — re-running it would re-snapshot what to restore
  // focus to and stamp inert a second time — so read onClose through a ref.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    const root = ref.current;
    if (!root) return;

    const restoreTo = document.activeElement as HTMLElement | null;

    const muted = [...document.body.children].filter(
      (el): el is HTMLElement => el !== root && el instanceof HTMLElement && !el.inert,
    );
    for (const el of muted) el.inert = true;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Somewhere to land before the sheet decides what deserves focus, so the
    // first Tab goes into the sheet rather than nowhere.
    root.tabIndex = -1;
    if (!root.contains(document.activeElement)) root.focus({ preventScroll: true });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);

    return () => {
      window.removeEventListener('keydown', onKey);
      for (const el of muted) el.inert = false;
      document.body.style.overflow = prevOverflow;
      // After un-inerting, or the element would refuse focus.
      restoreTo?.focus?.({ preventScroll: true });
    };
  }, []);

  return ref;
}
