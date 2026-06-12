import { useBudgets, useCategories, useInsights, useTransactions } from '../api/hooks';
import type { Category } from '../api/types';
import { BudgetBar } from '../components/BudgetBar';
import { Capture } from '../components/Capture';
import { CategoryAvatar } from '../components/CategoryAvatar';
import { AiBadge, BreathingDot } from '../components/bits';
import { Money } from '../components/Money';
import { Card, EmptyState } from '../components/ui';
import { categoryColor } from '../lib/categoryColor';
import { currentMonth, relativeDay } from '../lib/date';
import { formatMoney, moneyParts } from '../lib/money';

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

export function Home() {
  const month = currentMonth();
  const insights = useInsights(month);
  const budgets = useBudgets(month);
  const transactions = useTransactions({ month });
  const categories = useCategories();

  const catById = new Map<string, Category>((categories.data ?? []).map((c) => [c.id, c]));
  const catName = (id: string | null) => (id ? (catById.get(id)?.name ?? null) : null);

  const safe = insights.data?.safe_to_spend;
  const parts = safe ? moneyParts(safe.safe_to_spend_cents) : null;

  const today = new Date();
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const daysLeft = daysInMonth - today.getDate();
  const elapsedPct = (today.getDate() / daysInMonth) * 100;
  const monthName = today.toLocaleDateString('en-GB', { month: 'long' });
  const dateLong = today.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
  const perDay = safe && daysLeft > 0 ? Math.max(0, safe.safe_to_spend_cents) / daysLeft : 0;

  const totalDelta = (insights.data?.month_over_month ?? []).reduce((a, m) => a + m.delta_cents, 0);
  const aheadNote =
    totalDelta < 0
      ? `${formatMoney(-totalDelta)} ahead of last month`
      : totalDelta > 0
        ? `${formatMoney(totalDelta)} more than last month`
        : `${daysLeft} days left this month`;

  const recent = (transactions.data ?? []).slice(0, 5);

  return (
    <div className="animate-fade-up flex flex-col gap-[18px]">
      {/* Header */}
      <div className="flex items-end justify-between gap-5">
        <div>
          <div className="text-[14px] font-medium text-muted">{greeting()}</div>
          <h1 className="mt-0.5 font-display text-[26px] font-semibold tracking-[-0.02em] text-ink">
            {dateLong}
          </h1>
        </div>
        <div className="flex items-center gap-[7px]">
          <BreathingDot color={totalDelta <= 0 ? 'var(--go)' : 'var(--wait)'} />
          <span className="text-[13px] text-muted">{aheadNote}</span>
        </div>
      </div>

      {/* Safe-to-spend hero */}
      <Card className="px-8 py-[30px]">
        <div className="text-[13px] font-semibold tracking-[0.12em] text-muted uppercase">
          Safe to spend
        </div>
        {parts ? (
          <>
            <div className="num mt-2 flex items-start gap-0.5 leading-[0.9]">
              <span
                className="text-[84px] font-semibold tracking-[-0.03em]"
                style={{ color: parts.negative ? 'var(--over)' : 'var(--ink)' }}
              >
                {parts.negative ? '−' : ''}
                {parts.euros}
              </span>
              <span className="mt-1.5 text-[38px] font-semibold text-ink-2">,{parts.cents}</span>
              <span className="mt-[9px] ml-1.5 text-[32px] font-medium text-muted">€</span>
            </div>
            <div className="mt-1.5 text-[14.5px] text-ink-2">
              for the rest of {monthName} · <span className="num">{daysLeft}</span> days to go.{' '}
              {perDay > 0 && (
                <span className="text-muted">
                  That's about <Money cents={perDay} tone="muted" className="!text-[14.5px]" /> a
                  day.
                </span>
              )}
            </div>
            <MonthPulse elapsedPct={elapsedPct} daysInMonth={daysInMonth} monthName={monthName} />
          </>
        ) : (
          <p className="mt-3 text-muted">{insights.isError ? 'Could not load.' : 'Loading…'}</p>
        )}
      </Card>

      <Capture />

      {/* Recent + Budgets glance */}
      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.15fr_1fr]">
        <Card className="p-0">
          <div className="flex items-center justify-between px-[22px] pt-5 pb-1">
            <h2 className="text-[15px] font-semibold text-ink">Recent</h2>
            <span className="text-[13px] text-muted">last few</span>
          </div>
          <div className="px-[22px] pb-2">
            {recent.length > 0 ? (
              recent.map((t) => {
                const income = t.kind === 'income';
                const label = t.merchant ?? t.description;
                return (
                  <div
                    key={t.id}
                    className="flex items-center gap-[13px] border-b border-line py-3 last:border-0"
                  >
                    <CategoryAvatar
                      initial={label.charAt(0).toUpperCase()}
                      category={catName(t.category_id)}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-[7px] text-[14.5px] font-semibold text-ink">
                        <span className="truncate">{label}</span>
                        {t.source === 'nl_parse' && <AiBadge />}
                      </div>
                      <div className="text-[12.5px] text-muted">
                        {catName(t.category_id) ?? 'Uncategorised'} · {relativeDay(t.occurred_on)}
                      </div>
                    </div>
                    <Money
                      cents={income ? t.amount_cents : -t.amount_cents}
                      signed={income}
                      tone={income ? 'go' : 'default'}
                      className="!text-[16px] font-semibold"
                    />
                  </div>
                );
              })
            ) : (
              <p className="py-6 text-center text-[14px] text-muted">
                No transactions yet this month.
              </p>
            )}
          </div>
        </Card>

        <Card className="p-0">
          <div className="flex items-center justify-between px-[22px] pt-5 pb-3.5">
            <h2 className="text-[15px] font-semibold text-ink">Budgets</h2>
            {budgets.data && budgets.data.some((b) => !b.on_track) && (
              <span className="text-[12.5px] font-semibold text-wait">running hot</span>
            )}
          </div>
          <div className="flex flex-col gap-4 px-[22px] pb-5">
            {budgets.data && budgets.data.length > 0 ? (
              budgets.data.slice(0, 4).map((b) => (
                <div key={b.category_id}>
                  <div className="mb-[7px] flex items-center justify-between">
                    <div className="flex items-center gap-2 text-[14px] font-semibold text-ink">
                      <span
                        className="h-[9px] w-[9px] rounded-full"
                        style={{ background: categoryColor(b.category_name) }}
                      />
                      {b.category_name}
                    </div>
                    <div className="num text-[13px] text-muted">
                      <Money cents={b.spent_cents} tone="muted" className="!text-[13px]" /> /{' '}
                      <Money cents={b.limit_cents} tone="muted" className="!text-[13px]" />
                    </div>
                  </div>
                  <BudgetBar budget={b} />
                </div>
              ))
            ) : (
              <EmptyState title="No budgets yet" hint="Set monthly limits on the Budgets tab." />
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function MonthPulse({
  elapsedPct,
  daysInMonth,
  monthName,
}: {
  elapsedPct: number;
  daysInMonth: number;
  monthName: string;
}) {
  return (
    <div className="mt-5">
      <div className="relative h-1.5 overflow-hidden rounded-full bg-inset">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${elapsedPct}%`,
            background: 'linear-gradient(90deg, var(--line-2), var(--ink-2))',
          }}
        />
        <div
          className="absolute -top-[3px] h-3 w-0.5 rounded-sm bg-ink"
          style={{ left: `${elapsedPct}%` }}
        />
      </div>
      <div className="mt-[7px] flex justify-between text-[11.5px] text-muted">
        <span>{monthName} 1</span>
        <span>today</span>
        <span>
          {monthName} {daysInMonth}
        </span>
      </div>
    </div>
  );
}
