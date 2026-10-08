---
name: Протокол
description: Приватная расшифровка встреч — аудио → маскированный текст → LLM, всё локально
colors:
  primary: "#1d4ed8"
  primary-foreground: "#ffffff"
  foreground: "oklch(0.145 0 0)"
  background: "oklch(1 0 0)"
  muted: "oklch(0.97 0 0)"
  muted-foreground: "oklch(0.556 0 0)"
  border: "oklch(0.922 0 0)"
  destructive: "oklch(0.577 0.245 27.325)"
  ink: "#0f172a"
  paper: "#f1f5f9"
typography:
  body:
    fontFamily: '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif'
  label:
    fontFamily: '"SF Mono", "Cascadia Code", Consolas, "Liberation Mono", monospace'
    fontSize: "0.8125rem"
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "44px"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "44px"
  card:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "12px 16px"
  entity-chip:
    rounded: "{rounded.sm}"
    padding: "2px 8px"
  badge:
    rounded: "{rounded.pill}"
    padding: "2px 8px"
---

# Design System: Протокол

## Overview

**Creative North Star: "The Quiet Vault"**

The product is called **Протокол** — a private meeting transcriber. This is a trust instrument before it is a tool. The person using it is a banking executive handling other people's personal data; the interface must feel like a sealed, orderly vault — calm, exact, and quietly authoritative. Nothing decorative competes with the content. The visual restraint is the point: when the product's whole promise is "PII never leaves this machine," an interface that shouts undermines it. A quiet, precise surface reads as *safe to put sensitive audio into*. The header states the name and what it does (`Протокол` / `Приватная расшифровка встреч`); the pipeline mechanics live in the empty-state hint, not in the title.

The palette is deliberately near-monochrome — white paper, slate ink, a single controlled blue accent — with colour reserved almost entirely for one job: labelling the entities that get masked. That is the signature move. The saturated chips (PERSON blue, PHONE amber, documents red) are the only chromatic events on screen, and they exist to make privacy *visible*: you can see, at a glance, exactly what is being protected. Density is operational, not airy — this is an Operate-mode tool for 8–10 meetings a day, so three scannable panels beat a spacious hero every time.

**Key Characteristics:**
- Slate/blue restraint: near-monochrome chrome, one accent (`#1d4ed8`), colour spent only on masked-entity chips.
- Flat and border-driven: depth comes from 1px borders and a single subtle card shadow, never from glass or gradients.
- Mono for anything the machine produced: tokens, counts, and numbers render in a monospace face with tabular figures.
- Trilingual clarity: a Russian-language UI that stays legible at 375px and never overflows.
- Speaker turns (multi-speaker recordings) add structure without adding colour: monochrome turn rows with a number, not a hue.

## Colors

Near-monochrome slate-and-paper chrome, with a single disciplined accent and a saturated chip palette used only for masked entities.

### Primary
- **Vault Blue** (`#1d4ed8`): The one accent. Used on the primary button, the progress indicator fill, and the focus ring. Its rarity is deliberate — it marks the single next action or the active focus, never decoration.

### Neutral
- **Ink** (`oklch(0.145 0 0)` / `--foreground`, with `#0f172a` as `--color-ink`): Primary text and headings. Near-black, never pure black.
- **Paper** (`oklch(1 0 0)` / `--background`, with `#f1f5f9` as `--color-paper`): The page surface. Cards sit on white; the app background may cool to paper slate.
- **Quiet Slate** (`oklch(0.97 0 0)` / `--muted`): Secondary fills — badge backgrounds, the progress track, hover states.
- **Slate Text** (`oklch(0.556 0 0)` / `--muted-foreground`): Secondary copy, hints, metadata, percentages.
- **Hairline** (`oklch(0.922 0 0)` / `--border`): Every border and divider. This system separates with lines, not shadows.

### Destructive
- **Signal Red** (`oklch(0.577 0.245 27.325)` / `--destructive`): Error banners and invalid states only.

### Entity Chips (the signature colour system)
Colour appears here and almost nowhere else — these tint the tokens that get masked, making privacy visible.
- **PERSON** — blue (bg `#dbeafe`, text `#1e3a8a`, border `#93c5fd`): names.
- **ADDRESS** — green (bg `#dcfce7`, text `#14532d`, border `#86efac`): addresses.
- **PHONE** — amber (bg `#fef3c7`, text `#78350f`, border `#fcd34d`): phone numbers.
- **EMAIL** — violet (bg `#ede9fe`, text `#4c1d95`, border `#c4b5fd`): email addresses.
- **Documents** (PASSPORT / INN / SNILS / OMS / CARD / DRIVER_LICENSE / MILITARY_ID / BIRTH_CERTIFICATE) — red (bg `#fee2e2`, text `#7f1d1d`, border `#fca5a5`): identity and financial document numbers.
- **URL / IP** — slate (bg `#e2e8f0`, text `#0f172a`, border `#cbd5e1`): network identifiers.
- **OTHER** — quiet slate (bg `#f1f5f9`, text `#334155`, border `#cbd5e1`): anything unrecognised.

### Named Rules
**The One Accent Rule.** `#1d4ed8` marks exactly one thing per view — the primary action, the live progress, or the focus ring. It is never a background wash and never a second decorative hue.

**The Colour-Means-PII Rule.** Saturation on screen signals "this is masked data." If a coloured element is not labelling a masked entity, it is a mistake. Speaker labels follow it too: they stay monochrome, told apart by number and a neutral shade, never by a hue.

## Typography

**Display / Body / Heading Font:** Segoe UI (fallback `system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif`)
**Label / Mono Font:** SF Mono (fallback `"Cascadia Code", Consolas, "Liberation Mono", monospace`)

**Character:** A single humanist system sans carries all interface text — unshowy, maximally legible, native-feeling on the target MacBook. The pairing contrast is functional, not stylistic: the moment text is machine output (a mask token like `PERSON_1`, a token count, a percentage), it switches to a monospace face with tabular figures so numbers align and tokens read as code.

### Hierarchy
- **Title** (600 weight, ~`0.875rem`/14px, line-height tight): Panel and card headings — crisp, compact, sentence-case.
- **Body** (400 weight, `0.875rem`/14px): Transcript and reply prose; comfortable measure inside the panels.
- **Label** (400–500 weight, `0.8125rem`/13px mono, tabular): Mask tokens, counts ("2 токена"), percentages, and metadata. Uppercase is not used; the mono face alone signals "machine data."

### Named Rules
**The Mono-for-Machine Rule.** Anything the pipeline produced — token, number, score — renders in the mono face. Human prose never does. This is how the reader tells original text from system output at a glance.

## Layout

A centred shell capped at `max-w-7xl` (80rem / 1280px): a 260px session-history rail beside a main column, collapsing to one column below `lg`. The main column stacks top-to-bottom — drop-zone, then the three result panels in pipeline order. Spacing follows a tight 4/8px rhythm: `gap-2` (8px) for inline groups, `gap-3` (12px) between related rows, `space-y-5` / `gap-6` (24px) between panels. Card interiors use `px-4 py-3`; page bands use `py-6` / `py-8`.

The three result panels (transcript, masked text, model reply) stack in a single column, always in the order the pipeline runs; density is operational — content-first, minimal chrome, scannable top-to-bottom. When the recording has more than one speaker, the transcript panel becomes a list of speaker turns (see Speaker labels); a single-speaker recording keeps the plain transcript. The empty state is a centred dashed drop-zone rather than an empty grid.

The header is the product's identity line: the name (`Протокол`) with a one-line subtitle, and a single `Настройки` action on the right. Settings (model, OpenRouter key status) open as a quiet slate strip under the header, not a modal — they are set once and forgotten. The pipeline mechanics (`STT → PII → …`) are never the title; they belong in the empty-state hint.

The drop target has two states: a large dashed drop-zone when there is nothing on screen, and — once a result exists — a single compact row (`Перетащите сюда следующую запись или [Обработать ещё]`) so the result keeps the room. Both carry the same drag handlers; the file input lives once in the main column.

**The Order-Matches-Pipeline Rule.** Panels read left-to-right (or top-to-bottom when stacked) in the same order the data flows: transcript → masked → reply. Never rearrange them.

## Elevation & Depth

Essentially flat. Depth is conveyed by **1px borders** (`--border`, `#e2e8f0`-range) and subtle tonal shifts (`--muted` fills), not by shadow. There is exactly one shadow in the system: `shadow-sm` on the primary card surface (`0 1px 2px rgba(0,0,0,0.05)`), just enough to lift the working surface off the page. No glassmorphism, no gradients, no stacked elevation.

### Shadow Vocabulary
- **card-lift** (`box-shadow: 0 1px 2px rgba(0,0,0,0.05)` / Tailwind `shadow-sm`): The single permitted shadow, on the top-level card only.

### Named Rules
**The Border-First Rule.** Separate and contain with a 1px border before reaching for a shadow. If a shadow appears anywhere but the main card, it is wrong.

## Shapes

A gently curved, utilitarian form language. Radius derives from a `0.625rem` (10px) base: cards and drop-zones use `rounded-lg` (10px), buttons and inner chips use `rounded-md` (8px), and badges and the progress bar are full pills (`rounded-full`). Chips get the tightest corners (`rounded-sm`, 6px) so a token reads as an inline marker, not a button. Borders are straight 1px hairlines; the empty-state drop-zone switches to a `border-dashed` variant to invite a file drop.

## Components

### Buttons
- **Shape:** Gently rounded (`rounded-md`, 8px); minimum height 44px (`min-h-11`) for a comfortable pointer target; padding `10px 16px` (`px-4`).
- **Primary:** Solid Vault Blue (`bg-blue-700` / `#1d4ed8` family) with white text; on hover it darkens to `blue-800` and holds white text. This is the single accent per view.
- **Outline / Ghost:** White surface, slate-800 text, `#cbd5e1`-range border; hover fills to a faint slate (`bg-slate-50`). Used for secondary and cancel actions.
- **Focus:** A visible 2px outline in Vault Blue (`var(--ring)`) at 2px offset — the app's `.focus-ring` treatment.

### Cards / Containers
- **Corner Style:** `rounded-lg` (10px).
- **Background:** White (`--background`), edged with a 1px `slate-200` border.
- **Shadow Strategy:** The one permitted `shadow-sm` lift. Header is separated from content by a hairline (`border-b`).
- **Internal Padding:** Header `px-4 py-2.5`; content `px-4 py-3`. A small coloured accent dot (`h-2.5 w-2.5 rounded-full`) may mark a card's category.

### Chips / Entity Tags (signature)
- **Style:** Monospace (`0.8125rem`), tight `rounded-sm` corners, `2px 8px` padding, a 1px border matching the tint, and a saturated background with dark tone-on-tone text (see the Entity Chips palette).
- **State:** Stateless inline markers. Each entity type carries its fixed hue so the eye can scan for what was masked without reading.

### Badges
- **Style:** Full-pill (`rounded-full`), `2px 8px` padding, outline variant. Five tones — slate (neutral), green (success), amber (warning), red (error), blue (info) — each a light fill (`bg-*-50`) with a `*-200` border and dark `*-700/800/900` text.

### Speaker labels
- **Style:** A small `rounded-md` chip (`Спикер 1`, `Спикер 2`, …) with a 1px `slate-300` border, alternating `slate-100` / white fill, `slate-700` text; the turn's start time sits beneath it in `slate-400` mono (`tabular-nums`). Monochrome by rule: a hue here would collide with the entity chips, so speakers are told apart by number, not colour.
- **Placement:** When diarization finds more than one speaker, the transcript panel becomes a turn list — a fixed-width left rail (speaker chip + timestamp) beside the turn's text, entity chips still highlighting the PII inside each turn. One speaker, or no diarization model: the plain transcript, unchanged.

### Inputs / Fields
- **Style:** Standard monochrome fields on white with a 1px `--border` stroke and `rounded-md` corners.
- **Focus:** 2px Vault Blue outline at 2px offset (`.focus-ring`), consistent with buttons.

### Progress
- **Style:** A `h-2 rounded-full` track in `bg-slate-200` filled with the primary accent. The label row above pairs a short message (slate-600) with a right-aligned mono percentage (`tabular-nums`, slate-500).

### Empty State
- **Style:** A centred `rounded-lg` panel with a `border-dashed slate-300` edge and a faint `bg-white/60` fill — a calm drop target. Title in `text-sm font-medium slate-800`, hint beneath in `slate-500`.

### Settings strip
- **Style:** A `bg-slate-50` band under the header, separated by a `border-t` hairline. Inline labelled fields (`Модель LLM` text input, `Ключ OpenRouter` status in `emerald-700` / `amber-700`) and one explanatory line. In-flow, not a modal or a floating popover: it is opened by the header's `Настройки` button and forgotten once set.

### Session row
- **Style:** A full-width `rounded-md` selectable row (`border-slate-200`, hover `bg-slate-50`, active `border-blue-300 bg-blue-50`) with the file name on top and `date · N PII` beneath in `slate-500`. A monochrome `×` delete sits top-right as a sibling button (never nested inside the select button), appearing on hover; it removes the session and, if it was on screen, clears the result.

### Result actions
- **Style:** Small outline buttons in `slate-500` — `Скопировать` in a card header, `Скачать отчёт` at the right of the badges row. Text-only, no accent: copying and exporting are secondary to the content and must not compete with the one primary action. The report is a plain-text file (transcript + masked text + reply).

## Do's and Don'ts

### Do:
- **Do** spend colour only on masked-entity chips; keep every other surface slate/white.
- **Do** use the one accent (`#1d4ed8`) for exactly one primary action, the progress fill, or the focus ring per view.
- **Do** render tokens, counts, and scores in the mono face with tabular figures; keep prose in Segoe UI.
- **Do** separate content with 1px borders and tonal fills; reserve `shadow-sm` for the top-level card.
- **Do** keep panels ordered to match the pipeline (transcript → masked → reply) at every breakpoint.

### Don't:
- **Don't** decorate with the accent — no blue background washes, gradients, or a second brand hue.
- **Don't** colour anything that is not labelling masked data (see the Colour-Means-PII Rule).
- **Don't** add shadows, glass, or blur beyond the single card lift; this system is flat and border-driven.
- **Don't** put interface prose in the mono face, or machine tokens in the sans face.
- **Don't** let panels overflow their container — the 375px layout must stack cleanly with zero horizontal scroll.
