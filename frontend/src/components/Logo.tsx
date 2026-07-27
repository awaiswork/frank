/**
 * The Frankly mark: a monoline "f" carrying the brand's green full-stop — the
 * period from the wordmark, folded into a tile. `/favicon.svg` is the same
 * geometry with the colours baked in.
 *
 * The tile is `--ink` on `--paper`, so it inverts with the theme. The dot uses
 * `--mark-dot` rather than `--go` because it sits *on* the inverted tile: the
 * green that reads on the page would wash out on top of it.
 */
export function Mark({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="9" fill="var(--ink)" />
      <g stroke="var(--paper)" strokeWidth="3" strokeLinecap="round">
        <path d="M13.1 24V13c0-3.1 2.3-4.7 4.8-3.9" />
        <path d="M8.7 15.2h10" />
      </g>
      <circle cx="22.5" cy="23" r="2.4" fill="var(--mark-dot)" />
    </svg>
  );
}

/**
 * Mark + name. The mark already carries the full-stop, so the text doesn't
 * repeat it — the two together are the lockup.
 */
export function Wordmark({ size = 25 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2">
      <Mark size={Math.round(size * 1.1)} />
      <span
        className="font-display font-bold tracking-[-0.02em] text-ink"
        style={{ fontSize: `${size}px` }}
      >
        frankly
      </span>
    </div>
  );
}
