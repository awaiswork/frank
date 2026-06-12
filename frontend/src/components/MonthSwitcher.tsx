import { monthLabel, shiftMonth } from '../lib/date';

export function MonthSwitcher({
  month,
  onChange,
}: {
  month: string;
  onChange: (month: string) => void;
}) {
  const arrow =
    'grid h-8 w-8 place-items-center rounded-full border border-line-2 text-ink-2 hover:text-ink';
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className={arrow}
        aria-label="Previous month"
        onClick={() => onChange(shiftMonth(month, -1))}
      >
        ‹
      </button>
      <span className="min-w-[128px] text-center text-[13px] font-semibold text-ink-2">
        {monthLabel(month)}
      </span>
      <button
        type="button"
        className={arrow}
        aria-label="Next month"
        onClick={() => onChange(shiftMonth(month, 1))}
      >
        ›
      </button>
    </div>
  );
}
