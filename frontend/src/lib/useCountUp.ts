import { useEffect, useRef, useState } from 'react';

const prefersReduced =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

/**
 * Animate an integer toward `target` with an ease-out curve. Settles instantly on
 * first mount and under reduced-motion; only *subsequent* changes animate — so the
 * safe-to-spend figure ticks satisfyingly the moment you log, without a jarring
 * count-up on every page load.
 */
export function useCountUp(target: number, duration = 750): number {
  const [display, setDisplay] = useState(target);
  const displayRef = useRef(target);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (prefersReduced || displayRef.current === target) {
      displayRef.current = target;
      setDisplay(target);
      return;
    }
    const from = displayRef.current;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = Math.round(from + (target - from) * eased);
      displayRef.current = current;
      setDisplay(current);
      if (t < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration]);

  return display;
}
