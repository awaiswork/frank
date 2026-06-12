# Frank — Design System

Distilled from the design prototype (the "build specs" / redline screen). This is the
**source of truth for M2+ UI work** (technical-plan §9). Values are exact — implement them as
Tailwind theme extensions / CSS custom properties; don't eyeball them.

The prototype is a React + TypeScript single-page mock with light/dark themes driven entirely by
CSS custom properties under `[data-theme]`. Charts (donut, bars) are plain SVG/CSS primitives
styled to these tokens.

---

## Product shape (what the UI is for)

Frank is an AI spending advisor. The UI centres on two AI moments and the supporting money views:

- **Capture** — natural-language transaction entry. User types it like they'd say it
  ("8,40 coffee and croissant"); Frank parses amount / category / merchant / date into a **draft**
  the user confirms before anything saves. (Backs M3.)
- **Advisor ("Ask Frank")** — "Should I buy…" → Frank checks real budgets + goals, then returns one
  of four **verdicts** as a stamp with evidence and expandable reasoning. (Backs M4.)
- Supporting screens: Home (safe-to-spend), Transactions, Budgets, Goals, Insight, Settings,
  Onboarding (3 steps).

**Verdicts (signature concept)** — four outcomes, each readable *without color* via ring shape +
glyph + label:

| Verdict     | Token   | Ring (stroke-dasharray) | Glyph        | Meaning                         |
| ----------- | ------- | ----------------------- | ------------ | ------------------------------- |
| Go for it   | `--go`  | solid                   | arrow →      | well inside the lines           |
| Wait        | `--wait`| dashed `5 5`            | clock        | fits better after payday        |
| Skip        | `--skip`| double (dotted `2 6` + inner ring) | minus | a supportive no — **never red** |
| Your call   | `--call`| dotted `3 5`            | up/down chevrons | genuinely the user's decision |

Skip is deliberately a calm slate-blue, not red — Frank is non-judgmental.

---

## Currency & numbers

- Currency is **EUR**. Money is stored as **integer cents** (never floats) — matches the backend.
- All amounts render in **Space Grotesk** with `font-variant-numeric: tabular-nums lining-nums`.
- Thousands separator is a **thin space** (`U+202F`), decimal is a **comma**: `1 247,30 €`.
- Negative = spend, positive = income (income shown in `--go`).

---

## Typography

| Role           | Family               | Weight | Size                                              |
| -------------- | -------------------- | ------ | ------------------------------------------------- |
| Display        | Bricolage Grotesque  | 600/700| H1 22px; insight/goal headline 30px; verdict 34px/700 |
| Body & inputs  | Hanken Grotesk       | 400–700| **input 16px** (avoids iOS zoom); titles 14.5px/600; meta 13px/500 |
| Numbers        | Space Grotesk        | 400–700| safe-to-spend hero **84px** (cents 38px); tabular |
| Section label  | Hanken Grotesk       | 600    | 11–12px, UPPERCASE, letter-spacing `.1em`, `--muted` |

CSS var aliases used in the prototype: `--display`, `--body`, `--num`.
All three are Google Fonts — pull via `@fontsource/*` or Google Fonts in M2 (no need to vendor the
base64 the prototype embedded).

---

## Color tokens

Defined per `[data-theme="dark"]` / `[data-theme="light"]`. Dark is the prototype default.

| Token            | Dark      | Light     | Use                                   |
| ---------------- | --------- | --------- | ------------------------------------- |
| `--paper`        | `#161510` | `#F1EDE3` | App background                        |
| `--surface`      | `#1E1C15` | `#FFFFFF` | Cards, inputs                         |
| `--surface-2`    | `#262218` | `#F8F5EE` | Insets, nested                        |
| `--inset`        | `#211E16` | `#F4F1E8` | Track backgrounds (bars)              |
| `--ink`          | `#F3F0E7` | `#1B1A15` | Primary text, **solid buttons**       |
| `--ink-2`        | `#C9C4B5` | `#46443B` | Secondary text                        |
| `--muted`        | `#8E897A` | `#736F65` | Meta, labels                          |
| `--faint`        | `#615C50` | `#A8A399` | Faintest text                         |
| `--line`         | `#322E24` | `#E6E1D4` | Hairlines, card borders               |
| `--line-2`       | `#403A2D` | `#DAD4C5` | Stronger borders                      |
| `--field`        | `#211E16` | `#FCFBF7` | Input fill                            |
| `--go`           | `#63C68C` | `#1F7A4D` | Verdict: Go for it; income            |
| `--wait`         | `#E7B84B` | `#9A6A09` | Verdict: Wait; ahead-of-pace          |
| `--skip`         | `#84ABDB` | `#385E8F` | Verdict: Skip (calm, not red)         |
| `--call`         | `#B098F0` | `#5A45B4` | Verdict: Your call                    |
| `--over`         | `#E2865C` | `#C2562F` | Overspent (factual, not alarm)        |
| `--cat-grocery`  | `#9BC85F` | `#5E8C2E` | Category: Groceries                   |
| `--cat-dining`   | `#E8995A` | `#BF6A2C` | Category: Eating out                  |
| `--cat-transport`| `#62B0CE` | `#2A7C9C` | Category: Transport                   |
| `--cat-fun`      | `#DB85C6` | `#B4519E` | Category: Fun                         |
| `--cat-bills`    | `#9C97B4` | `#67637F` | Category: Bills                       |
| `--cat-savings`  | `#E7C24B` | `#9C7507` | Category: Savings                     |
| `--cat-health`   | `#E58BA0` | `#B14A5C` | Category: Health                      |
| `--focus`        | `#E7C24B` | `#9A6A09` | Focus ring                            |

**Soft tints** back verdict headers and "frank" callouts:
`--go-soft` `#15291E`/`#E6F1EA`, `--wait-soft` `#2A2310`/`#F4ECD9`, `--skip-soft` `#15212E`/`#E8EDF6`,
`--call-soft` `#211B31`/`#ECE8F8`, `--over-soft` `#2C1C12`/`#F7E7DF`.

**Category tints** (icon chips) use `color-mix(in oklab, <cat> 16%, transparent)`.

Color encodes meaning, never mood. There is **no brand-color button** — the primary button is solid
`--ink`.

---

## Spacing, radius, shadow

- **Spacing scale:** 4 · 8 · 12 · 16 · 24 · 32 px.
- **Radius:** `--r` 16px (cards), `--r-s` 11px (inputs/chips), `999px` (pills), 1px hairline `--line`.
- **Shadow:** `--shadow` — soft, low: e.g. dark `0 1px 0 rgba(255,255,255,.03), 0 18px 40px -24px rgba(0,0,0,.7)`.

---

## Motion

- **Ease (all):** `cubic-bezier(.2,.8,.2,1)` → `--ease`.
- Micro (hover, expand): 150–250ms.
- Screen enter (`fadeUp`): 300–400ms.
- Draft fields (`fieldIn`): 500ms, **80ms stagger** between fields.
- Verdict stamp (`stampIn`): 600ms — rotates in, settles at **−8°**.
- Bars (`barGrow`): 800ms via `transform: scaleX` (origin left) — width data stays exact.
- Toast: auto-dismiss 2.2–2.6s, fixed bottom-center 28px up.
- **`prefers-reduced-motion`:** all durations collapse to ~0. One orchestrated moment per flow,
  never scattered effects.

---

## Components (redlines)

- **Buttons:** h 44–50, radius 11–13, pad `0 20`. Primary = solid `--ink` on `--paper`.
  Secondary = `--surface` + `1px --line-2`, `--ink-2`. Ghost = text only. Labels name the action
  ("Save transaction", "Log it"), never "Submit".
- **Input:** 16px, pad `9 0`, inside a `--surface` + `1px --line-2` shell radius `--r`, with the
  primary button tucked on the right.
- **Chips / filter:** pad `7 14`, pill. Active = solid `--ink`; inactive = `--surface` + `1px --line-2`.
- **Budget bar (time-aware):** track 8px / 999, fill animates `barGrow`. A 2px pace marker sits at
  `elapsed-days / days-in-month`. Fill **behind** marker → on pace (`--go`); **past** marker →
  ahead of pace (`--wait`); **full** (capped 100%) → overspent (`--over`). Factual, not alarm.
- **Verdict stamp:** 92px, ring stroke 3, glyph stroke 4.5; header bg is the matching `--*-soft`.
- **Draft field:** each field taps to correct in place; enters `fieldIn` 80ms apart. Confidence reads
  **sure** (`--go`) / **fairly sure** (`--wait`) / **a guess** (`--over`).
- **Goal card:** saved / target + ETA. On reached → bar + border flip to `--go`, label "Funded",
  no confetti.
- **Toast:** solid `--ink`, confirms a budget impact ("Groceries: 64% → 71%"), then auto-dismisses.

---

## Categories (also feed the M3 parser)

The prototype's parser maps keywords → category; reuse this taxonomy. Each has a color token above.

| Key        | Label      | Example keywords (non-exhaustive)                          |
| ---------- | ---------- | ---------------------------------------------------------- |
| groceries  | Groceries  | k-market, lidl, prisma, grocery, milk, bread               |
| dining     | Eating out | lunch, dinner, coffee, restaurant, pizza, beer, kebab      |
| transport  | Transport  | bus, train, vr, tram, taxi, uber, bolt, fuel               |
| fun        | Fun        | cinema, movie, concert, book, museum, bar                  |
| bills      | Bills      | spotify, netflix, rent, electricity, phone, insurance, gym |
| health     | Health     | pharmacy, doctor, dentist, medicine                        |
| income     | Income     | salary, paid, refund, bonus                                |
| savings    | Savings    | fund, savings, save (+ named goals, e.g. "Lisbon")         |

---

## Accessibility floor (non-negotiable)

- Focus ring: `2px solid var(--focus)`, offset 2px, on every interactive element.
- Touch targets ≥ 44px (primary buttons 44–50px tall).
- The four verdicts read without color (ring shape + glyph + label).
- AA contrast on all verdict colors in both modes; safe-to-spend figure ≥ 80px.
- Entire capture flow keyboard-operable; inputs at 16px to avoid mobile zoom.
