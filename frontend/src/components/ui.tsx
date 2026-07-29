import { createPortal } from 'react-dom';
import type { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, ReactNode } from 'react';

/**
 * Renders children on <body>, outside the page tree.
 *
 * Every overlay must go through this. `position: fixed` is resolved against the
 * nearest ancestor with a transform, not the viewport — and each page root
 * carries `animate-fade-up`, whose `both` fill leaves a transform applied for
 * good. A sheet rendered inside a page therefore centres itself on that page's
 * column and gets clipped by its height, which is exactly what it looks like.
 * Escaping to <body> means no ancestor can ever capture it again.
 */
export function Portal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body);
}

/**
 * The surface everything sits on — and a **container query context**, so what's
 * inside can size itself against this card rather than the viewport. A card in
 * Home's narrow right-hand column and the same card full-width on Transactions
 * are different amounts of room; `cqi` units let one component answer both
 * without a media query that can only ever see the window.
 *
 * `container-type: inline-size` also applies `contain: layout`, which would make
 * this a containing block for any `position: fixed` descendant. That is safe
 * here only because every overlay already escapes to <body> through `Portal` —
 * see its note above. Keep it that way.
 */
export function Card({
  children,
  className = '',
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className={`@container rounded-card border border-line bg-surface p-5 ${className}`}
      style={{ boxShadow: 'var(--shadow)', ...style }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">{children}</p>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost';
};

export function Button({ variant = 'primary', className = '', ...props }: ButtonProps) {
  const base =
    'inline-flex h-11 items-center justify-center rounded-input px-5 text-[14.5px] font-semibold transition-opacity disabled:opacity-50';
  const styles: Record<NonNullable<ButtonProps['variant']>, string> = {
    primary: 'bg-ink text-paper hover:opacity-90',
    secondary: 'border border-line-2 bg-surface text-ink-2 hover:text-ink',
    ghost: 'text-ink-2 hover:text-ink',
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

export function TextInput({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-11 w-full rounded-input border border-line-2 bg-field px-3 text-[16px] text-ink placeholder:text-faint ${className}`}
      {...props}
    />
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] font-medium text-ink-2">{label}</span>
      {children}
    </label>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-card border border-dashed border-line-2 px-5 py-10 text-center">
      <p className="text-[14.5px] font-semibold text-ink-2">{title}</p>
      {hint && <p className="mt-1 text-[13px] text-muted">{hint}</p>}
    </div>
  );
}
