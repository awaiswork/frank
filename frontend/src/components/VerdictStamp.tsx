import type { VerdictKind } from '../api/types';
import { VERDICT_SPEC } from '../lib/verdict';

/**
 * The signature verdict stamp (design §verdicts). Each verdict is distinguishable
 * WITHOUT colour — by ring pattern (stroke-dasharray) + glyph + label. Skip is a
 * calm slate-blue, never red.
 */
function Glyph({ verdict }: { verdict: VerdictKind }) {
  const p = {
    stroke: 'currentColor',
    fill: 'none',
    strokeWidth: 4.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  switch (verdict) {
    case 'go':
      return <path d="M32 46 H60 M50 35 L61 46 L50 57" {...p} />;
    case 'wait':
      return (
        <>
          <circle cx="46" cy="46" r="13" {...p} strokeWidth={3.5} />
          <path d="M46 39 V47 L52 50" {...p} strokeWidth={3.5} />
        </>
      );
    case 'skip':
      return <path d="M34 46 H58" {...p} />;
    case 'your_call':
      return (
        <>
          <path d="M37 44 L46 35 L55 44" {...p} />
          <path d="M37 52 L46 61 L55 52" {...p} />
        </>
      );
  }
}

export function VerdictStamp({
  verdict,
  size = 92,
  animate = false,
  label = true,
}: {
  verdict: VerdictKind;
  size?: number;
  animate?: boolean;
  label?: boolean;
}) {
  const s = VERDICT_SPEC[verdict];
  return (
    <div className="flex flex-col items-center gap-2">
      <svg
        width={size}
        height={size}
        viewBox="0 0 92 92"
        fill="none"
        style={{ color: s.color }}
        className={animate ? 'animate-stamp' : ''}
        role="img"
        aria-label={`${s.label} verdict`}
      >
        <circle
          cx="46"
          cy="46"
          r="42"
          stroke="currentColor"
          strokeWidth="3"
          strokeDasharray={s.dash}
        />
        {s.double && <circle cx="46" cy="46" r="34" stroke="currentColor" strokeWidth="2.5" />}
        <Glyph verdict={verdict} />
      </svg>
      {label && (
        <span className="text-[13px] font-semibold" style={{ color: s.color }}>
          {s.label}
        </span>
      )}
    </div>
  );
}
