import { formatMoney } from '../lib/money';

type Tone = 'default' | 'go' | 'over' | 'muted';

export function Money({
  cents,
  signed = false,
  tone = 'default',
  className = '',
}: {
  cents: number;
  signed?: boolean;
  tone?: Tone;
  className?: string;
}) {
  const toneClass: Record<Tone, string> = {
    default: 'text-ink',
    go: 'text-go',
    over: 'text-over',
    muted: 'text-muted',
  };
  return (
    <span className={`num ${toneClass[tone]} ${className}`}>{formatMoney(cents, { signed })}</span>
  );
}
