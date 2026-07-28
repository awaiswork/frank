import { useEffect, useMemo, useState } from 'react';
import { Navigate, NavLink, Outlet } from 'react-router-dom';
import { useFeatures } from '../api/hooks';
import { useAuth } from '../auth/useAuth';
import { CaptureContext } from '../capture/CaptureContext';
import { AmbientField } from './AmbientField';
import { Wordmark } from './Logo';
import { QuickAdd } from './QuickAdd';
import { Portal } from './ui';

type IconName = 'home' | 'advisor' | 'transactions' | 'budgets' | 'goals' | 'insight' | 'settings';

function Icon({ name }: { name: IconName }) {
  const p = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  switch (name) {
    case 'home':
      return (
        <svg {...p}>
          <path d="M3 10.5 12 3l9 7.5V21H3z" />
          <path d="M9 21v-7h6v7" />
        </svg>
      );
    case 'advisor':
      return (
        <svg {...p}>
          <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
          <path d="M12 8v3M12 14h.01" />
        </svg>
      );
    case 'transactions':
      return (
        <svg {...p}>
          <path d="M8 6h13M8 12h13M8 18h13" />
          <path d="M3 6h.01M3 12h.01M3 18h.01" />
        </svg>
      );
    case 'budgets':
      return (
        <svg {...p}>
          <path d="M3 3v18h18" />
          <rect x="7" y="11" width="3" height="6" />
          <rect x="13" y="7" width="3" height="10" />
        </svg>
      );
    case 'goals':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="12" r="5" />
          <circle cx="12" cy="12" r="1" />
        </svg>
      );
    case 'insight':
      return (
        <svg {...p}>
          <path d="M3 17l5-5 4 4 7-7" />
          <path d="M16 6h5v5" />
        </svg>
      );
    case 'settings':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H1a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 2.6 7a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H7a1.6 1.6 0 0 0 1-1.5V1a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V7a1.6 1.6 0 0 0 1.5 1H23a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" />
        </svg>
      );
  }
}

function useTheme(): ['dark' | 'light', () => void] {
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (document.documentElement.getAttribute('data-theme') as 'dark' | 'light') || 'dark',
  );
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try {
      localStorage.setItem('frankly-theme', next);
    } catch {
      /* ignore */
    }
    setTheme(next);
  };
  return [theme, toggle];
}

const PRIMARY: ReadonlyArray<readonly [string, string, IconName]> = [
  ['/', 'Home', 'home'],
  ['/advisor', 'Ask Frankly', 'advisor'],
];
const RECORDS: ReadonlyArray<readonly [string, string, IconName]> = [
  ['/transactions', 'Transactions', 'transactions'],
  ['/budgets', 'Budgets', 'budgets'],
  ['/goals', 'Goals', 'goals'],
  ['/insights', 'Insight', 'insight'],
  ['/settings', 'Settings', 'settings'],
];

function NavItem({
  to,
  label,
  icon,
  soon = false,
}: {
  to: string;
  label: string;
  icon: IconName;
  soon?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-[11px] px-3 py-2.5 text-[15px] font-semibold transition-colors ${
          isActive ? 'bg-surface text-ink' : 'text-muted hover:text-ink-2'
        }`
      }
    >
      <span className="grid h-[18px] w-[18px] place-items-center">
        <Icon name={icon} />
      </span>
      {label}
      {soon && (
        <span
          title="Coming soon"
          className="ml-auto rounded-full bg-inset px-1.5 py-px text-[9.5px] font-bold tracking-[0.08em] text-faint uppercase"
        >
          Soon
        </span>
      )}
    </NavLink>
  );
}

export function Layout() {
  const { logout, user } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const { features, ready } = useFeatures();
  const [adding, setAdding] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const advisorSoon = ready && !features.advisor;

  // The one handle screens get on the capture sheet, so there is only ever one.
  const capture = useMemo(() => ({ open: () => setAdding(true) }), []);

  // Logging is the thing people open Frankly to do, so it gets a global shortcut:
  // "a" for add (ignored while typing, so it never eats a keystroke) and ⌘/Ctrl-K.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing =
        el != null &&
        (el.tagName === 'INPUT' ||
          el.tagName === 'TEXTAREA' ||
          el.tagName === 'SELECT' ||
          el.isContentEditable);
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setAdding(true);
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        setAdding(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // First-run users (no income yet) land in onboarding until they finish or skip.
  const needsOnboarding =
    user != null && user.monthly_income_cents == null && !localStorage.getItem('frankly-onboarded');
  if (needsOnboarding) return <Navigate to="/onboarding" replace />;

  const today = new Date();
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const daysLeft = daysInMonth - today.getDate();
  const elapsed = (today.getDate() / daysInMonth) * 100;
  const monthName = today.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

  const themeIcon =
    theme === 'dark' ? (
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    ) : (
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
    );

  const wordmark = <Wordmark />;

  return (
    <CaptureContext.Provider value={capture}>
      <AmbientField />
      <div className="relative z-10 min-h-svh">
        {/* Mobile top bar — the sidebar's identity + theme, without its footprint */}
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-paper/85 px-4 py-3 backdrop-blur-md lg:hidden">
          {wordmark}
          <button
            onClick={toggleTheme}
            aria-label="Toggle light and dark"
            className="grid h-10 w-10 place-items-center rounded-[10px] border border-line bg-surface text-ink-2"
          >
            {themeIcon}
          </button>
        </header>

        <div className="mx-auto grid max-w-[1180px] grid-cols-1 items-start lg:grid-cols-[236px_1fr]">
          {/* Sidebar (desktop only) */}
          <aside className="sticky top-0 hidden h-svh flex-col gap-7 border-r border-line px-5 py-[26px] lg:flex">
            <div className="flex items-center justify-between">
              {wordmark}
              <button
                onClick={toggleTheme}
                aria-label="Toggle light and dark"
                className="grid h-[38px] w-[38px] place-items-center rounded-[10px] border border-line bg-surface text-ink-2 hover:text-ink"
              >
                {themeIcon}
              </button>
            </div>

            {/* Logging is the primary action, so it sits above navigation. */}
            <button
              onClick={() => setAdding(true)}
              className="flex h-11 items-center justify-center gap-2 rounded-input bg-ink text-[14.5px] font-semibold text-paper transition-opacity hover:opacity-90"
            >
              <PlusIcon />
              Log an expense
              <kbd className="ml-1 rounded border border-paper/25 px-1 py-px font-sans text-[10px] font-bold opacity-70">
                A
              </kbd>
            </button>

            <nav className="flex flex-col gap-[3px]">
              {PRIMARY.map(([to, label, icon]) => (
                <NavItem
                  key={to}
                  to={to}
                  label={label}
                  icon={icon}
                  soon={to === '/advisor' && advisorSoon}
                />
              ))}
              <div className="mx-1 my-2.5 h-px bg-line" />
              {RECORDS.map(([to, label, icon]) => (
                <NavItem key={to} to={to} label={label} icon={icon} />
              ))}
            </nav>

            <div className="mt-auto flex flex-col gap-2.5">
              <div className="rounded-[13px] border border-line bg-surface p-3.5">
                <div className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">
                  This month
                </div>
                <div className="num mt-1.5 text-[15px] font-semibold text-ink">{monthName}</div>
                <div className="mt-2.5 flex items-center gap-2">
                  <div className="relative h-[5px] flex-1 overflow-hidden rounded-full bg-inset">
                    <div
                      className="absolute inset-y-0 left-0 rounded-full bg-ink-2"
                      style={{ width: `${elapsed}%` }}
                    />
                  </div>
                  <span className="num text-[12px] text-muted">{daysLeft} left</span>
                </div>
              </div>
              <button
                onClick={logout}
                className="px-1.5 text-left text-[12.5px] font-semibold text-muted hover:text-ink"
              >
                Sign out
              </button>
            </div>
          </aside>

          {/* Main. Bottom padding clears the mobile tab bar. */}
          <main className="min-h-svh px-4 pt-6 pb-32 sm:px-6 lg:px-11 lg:pt-10 lg:pb-20">
            <Outlet />
          </main>
        </div>
      </div>

      {/* Mobile tab bar, with logging as the centre of gravity */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex items-stretch justify-around border-t border-line bg-paper/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
        <TabItem to="/" label="Home" icon="home" />
        <TabItem to="/transactions" label="Activity" icon="transactions" />
        <li className="flex min-w-0 flex-1 items-center justify-center">
          <button
            onClick={() => setAdding(true)}
            aria-label="Log an expense"
            className="-mt-6 grid h-14 w-14 place-items-center rounded-full bg-ink text-paper"
            style={{ boxShadow: '0 8px 24px rgba(0,0,0,0.35)' }}
          >
            <PlusIcon size={26} />
          </button>
        </li>
        <TabItem to="/budgets" label="Budgets" icon="budgets" />
        <li className="flex min-w-0 flex-1">
          <button
            onClick={() => setMoreOpen(true)}
            className="flex w-full flex-col items-center gap-1 py-2.5 text-[10.5px] font-semibold text-muted"
          >
            <span className="grid h-[22px] w-[22px] place-items-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="5" cy="12" r="1.8" />
                <circle cx="12" cy="12" r="1.8" />
                <circle cx="19" cy="12" r="1.8" />
              </svg>
            </span>
            More
          </button>
        </li>
      </nav>

      {moreOpen && (
        <MoreSheet
          advisorSoon={advisorSoon}
          onClose={() => setMoreOpen(false)}
          onSignOut={logout}
          monthName={monthName}
          daysLeft={daysLeft}
        />
      )}

      <QuickAdd open={adding} onClose={() => setAdding(false)} />
    </CaptureContext.Provider>
  );
}

function PlusIcon({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

/** One tab in the mobile bar. Wrapped in <li> so the bar is a real list. */
function TabItem({ to, label, icon }: { to: string; label: string; icon: IconName }) {
  return (
    <li className="flex min-w-0 flex-1">
      <NavLink
        to={to}
        end={to === '/'}
        className={({ isActive }) =>
          `flex w-full flex-col items-center gap-1 py-2.5 text-[10.5px] font-semibold transition-colors ${
            isActive ? 'text-ink' : 'text-muted'
          }`
        }
      >
        <span className="grid h-[22px] w-[22px] place-items-center">
          <Icon name={icon} />
        </span>
        {label}
      </NavLink>
    </li>
  );
}

/** The rest of the nav on small screens, so the tab bar stays down to five slots. */
function MoreSheet({
  advisorSoon,
  onClose,
  onSignOut,
  monthName,
  daysLeft,
}: {
  advisorSoon: boolean;
  onClose: () => void;
  onSignOut: () => void;
  monthName: string;
  daysLeft: number;
}) {
  const items: ReadonlyArray<readonly [string, string, IconName]> = [
    ['/advisor', 'Ask Frankly', 'advisor'],
    ['/goals', 'Goals', 'goals'],
    ['/insights', 'Insight', 'insight'],
    ['/settings', 'Settings', 'settings'],
  ];
  return (
    <Portal>
      <div className="fixed inset-0 z-40 flex items-end lg:hidden" role="dialog" aria-modal="true">
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="animate-fade-in absolute inset-0 cursor-default bg-black/45"
        />
        <div className="animate-sheet-in relative max-h-[92svh] w-full overflow-y-auto rounded-t-[22px] border border-line-2 bg-surface px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">
                This month
              </div>
              <div className="num text-[15px] font-semibold text-ink">
                {monthName} · {daysLeft} days left
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="grid h-9 w-9 place-items-center rounded-full text-muted"
            >
              <svg
                width="17"
                height="17"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
              >
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="flex flex-col">
            {items.map(([to, label, icon]) => (
              <NavLink
                key={to}
                to={to}
                onClick={onClose}
                className="flex items-center gap-3 border-b border-line py-3.5 text-[15px] font-semibold text-ink last:border-0"
              >
                <span className="grid h-[18px] w-[18px] place-items-center text-muted">
                  <Icon name={icon} />
                </span>
                {label}
                {to === '/advisor' && advisorSoon && (
                  <span className="ml-auto rounded-full bg-inset px-1.5 py-px text-[9.5px] font-bold tracking-[0.08em] text-faint uppercase">
                    Soon
                  </span>
                )}
              </NavLink>
            ))}
          </div>
          <button
            onClick={onSignOut}
            className="mt-3 h-11 w-full rounded-input border border-line-2 text-[14px] font-semibold text-ink-2"
          >
            Sign out
          </button>
        </div>
      </div>
    </Portal>
  );
}
