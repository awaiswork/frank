import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCategories, useCreateGoal, useUpdateMe, useUpsertBudget } from '../api/hooks';
import type { Category } from '../api/types';
import { useAuth } from '../auth/useAuth';
import { Button, TextInput } from '../components/ui';
import { categoryColor } from '../lib/categoryColor';
import { currentMonth } from '../lib/date';
import { formatMoney, parseAmountToCents } from '../lib/money';

const STEPS = 3;

export function Onboarding() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const categories = useCategories();
  const updateMe = useUpdateMe();
  const upsertBudget = useUpsertBudget(currentMonth());
  const createGoal = useCreateGoal();

  const [step, setStep] = useState(0);
  const [income, setIncome] = useState(
    user?.monthly_income_cents != null ? String(user.monthly_income_cents / 100) : '',
  );
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [goalName, setGoalName] = useState('');
  const [goalTarget, setGoalTarget] = useState('');
  const [goalDue, setGoalDue] = useState('');

  const incomeCents = parseAmountToCents(income) ?? 0;
  const expenseCats = (categories.data ?? []).filter((c) => c.kind === 'expense');
  const busy = updateMe.isPending || upsertBudget.isPending || createGoal.isPending;

  function finish() {
    try {
      localStorage.setItem('frank-onboarded', '1');
    } catch {
      /* ignore */
    }
    navigate('/', { replace: true });
  }

  function toggle(cat: Category) {
    setPicked((prev) => {
      const next = { ...prev };
      if (cat.id in next) {
        delete next[cat.id];
      } else {
        next[cat.id] = suggestEuros(cat.name, incomeCents);
      }
      return next;
    });
  }

  async function handleNext() {
    if (step === 0) {
      const cents = parseAmountToCents(income);
      if (cents == null) return;
      const updated = await updateMe.mutateAsync({ monthly_income_cents: cents });
      setUser(updated);
      setStep(1);
      return;
    }
    if (step === 1) {
      const writes = Object.entries(picked)
        .map(([categoryId, amount]) => ({ categoryId, limitCents: parseAmountToCents(amount) }))
        .filter((w): w is { categoryId: string; limitCents: number } => w.limitCents != null);
      await Promise.all(writes.map((w) => upsertBudget.mutateAsync(w)));
      setStep(2);
      return;
    }
    // step 2 — goal is optional
    const target = parseAmountToCents(goalTarget);
    if (goalName.trim() && target != null) {
      await createGoal.mutateAsync({
        name: goalName.trim(),
        target_cents: target,
        due_date: goalDue || null,
      });
    }
    finish();
  }

  const canAdvance = step === 0 ? parseAmountToCents(income) != null : true;

  return (
    <div className="grid min-h-svh place-items-center px-5 py-10">
      <div className="animate-fade-up w-full max-w-[440px]">
        {/* Wordmark + progress */}
        <div className="mb-7 flex flex-col items-center gap-4">
          <div className="flex items-baseline gap-px">
            <span className="font-display text-[26px] font-bold tracking-[-0.02em] text-ink">
              frank
            </span>
            <span className="font-display text-[26px] font-bold text-go">.</span>
          </div>
          <div className="flex w-full max-w-[220px] gap-1.5">
            {Array.from({ length: STEPS }, (_, i) => (
              <div
                key={i}
                className={`h-[5px] flex-1 rounded-full transition-colors duration-500 ${
                  i <= step ? 'bg-go' : 'bg-inset'
                }`}
              />
            ))}
          </div>
        </div>

        <div
          key={step}
          className="animate-fade-up rounded-card border border-line bg-surface p-7"
          style={{ boxShadow: 'var(--shadow)' }}
        >
          {step === 0 && (
            <Step
              eyebrow="Welcome"
              title="What do you earn each month?"
              blurb="After tax, roughly. Frank uses it to figure out what's safe to spend — you can change it any time."
            >
              <MoneyInput value={income} onChange={setIncome} placeholder="3200" autoFocus />
            </Step>
          )}

          {step === 1 && (
            <Step
              eyebrow="Your spending"
              title="Where does it usually go?"
              blurb="Pick the categories you spend on. We'll suggest a starting budget — tweak any of them."
            >
              <div className="flex flex-col gap-2">
                {expenseCats.map((c) => {
                  const on = c.id in picked;
                  return (
                    <div
                      key={c.id}
                      className={`flex items-center gap-3 rounded-input border px-3.5 py-2.5 transition-colors ${
                        on ? 'border-line-2 bg-inset' : 'border-line'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => toggle(c)}
                        className="flex flex-1 items-center gap-3 text-left"
                      >
                        <span
                          className="grid h-5 w-5 place-items-center rounded-md border-2 transition-colors"
                          style={{
                            borderColor: on ? categoryColor(c.name) : 'var(--line-2)',
                            background: on ? categoryColor(c.name) : 'transparent',
                          }}
                        >
                          {on && (
                            <svg
                              width="11"
                              height="11"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="var(--paper)"
                              strokeWidth="3.5"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M5 12l5 5L20 6" />
                            </svg>
                          )}
                        </span>
                        <span className="text-[14.5px] font-medium text-ink">{c.name}</span>
                      </button>
                      {on && (
                        <div className="animate-field-in relative w-[110px]">
                          <span className="absolute top-1/2 left-2.5 -translate-y-1/2 text-[13px] text-muted">
                            €
                          </span>
                          <input
                            inputMode="decimal"
                            value={picked[c.id]}
                            onChange={(e) => setPicked((p) => ({ ...p, [c.id]: e.target.value }))}
                            className="num h-9 w-full rounded-md border border-line-2 bg-field pr-2 pl-6 text-right text-[14px] text-ink"
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              {Object.keys(picked).length > 0 && (
                <p className="mt-3 text-[13px] text-muted">
                  Budgeted so far:{' '}
                  <span className="num font-semibold text-ink-2">
                    {formatMoney(pickedTotal(picked))}
                  </span>
                </p>
              )}
            </Step>
          )}

          {step === 2 && (
            <Step
              eyebrow="One more thing"
              title="Saving for something?"
              blurb="Optional. Add a goal and Frank will weigh it before telling you to splurge."
            >
              <div className="flex flex-col gap-3">
                <TextInput
                  value={goalName}
                  onChange={(e) => setGoalName(e.target.value)}
                  placeholder="e.g. Japan trip"
                  maxLength={60}
                />
                <div className="flex gap-2.5">
                  <MoneyInput value={goalTarget} onChange={setGoalTarget} placeholder="2500" />
                  <input
                    type="date"
                    value={goalDue}
                    onChange={(e) => setGoalDue(e.target.value)}
                    className="num h-11 rounded-input border border-line-2 bg-field px-3 text-[14px] text-ink-2"
                  />
                </div>
              </div>
            </Step>
          )}

          {/* Footer */}
          <div className="mt-7 flex items-center gap-3">
            {step > 0 && (
              <Button variant="ghost" onClick={() => setStep((s) => s - 1)} disabled={busy}>
                Back
              </Button>
            )}
            <div className="flex-1" />
            <Button variant="ghost" onClick={finish} disabled={busy}>
              {step === STEPS - 1 ? 'Skip' : 'Skip for now'}
            </Button>
            <Button onClick={handleNext} disabled={!canAdvance || busy}>
              {busy ? 'Saving…' : step === STEPS - 1 ? 'Finish' : 'Continue'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Step({
  eyebrow,
  title,
  blurb,
  children,
}: {
  eyebrow: string;
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-[11px] font-bold tracking-[0.14em] text-muted uppercase">{eyebrow}</p>
        <h1 className="mt-2 font-display text-[23px] leading-[1.2] font-semibold tracking-[-0.02em] text-balance">
          {title}
        </h1>
        <p className="mt-2 text-[14.5px] leading-relaxed text-muted text-pretty">{blurb}</p>
      </div>
      {children}
    </div>
  );
}

function MoneyInput({
  value,
  onChange,
  placeholder,
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  return (
    <div className="relative flex-1">
      <span className="absolute top-1/2 left-3.5 -translate-y-1/2 text-[16px] text-muted">€</span>
      <TextInput
        autoFocus={autoFocus}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="num pl-8"
      />
    </div>
  );
}

function suggestEuros(name: string, incomeCents: number): string {
  const n = name.toLowerCase();
  const frac =
    n.includes('rent') || n.includes('bill') || n.includes('housing')
      ? 0.3
      : n.includes('grocer')
        ? 0.12
        : n.includes('eat') || n.includes('dining') || n.includes('restaurant')
          ? 0.08
          : n.includes('transport') || n.includes('car') || n.includes('fuel')
            ? 0.07
            : n.includes('saving')
              ? 0.1
              : n.includes('shop')
                ? 0.08
                : n.includes('health')
                  ? 0.05
                  : 0.06;
  const euros = incomeCents > 0 ? Math.round((incomeCents / 100) * frac) : 100;
  const rounded = Math.max(Math.round(euros / 5) * 5, 10);
  return String(rounded);
}

function pickedTotal(picked: Record<string, string>): number {
  return Object.values(picked).reduce((sum, v) => sum + (parseAmountToCents(v) ?? 0), 0);
}
