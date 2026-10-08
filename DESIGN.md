---
name: Протокол
description: Приватная расшифровка встреч — аудио → маскированный текст → LLM, всё локально
colors:
  primary: "#1d4ed8"
  primary-foreground: "#ffffff"
  foreground: "#0f172a"
  background: "#ffffff"
  paper: "#f1f5f9"
  muted-foreground: "#64748b"
  border: "#e2e8f0"
  destructive: "#b91c1c"
  dark:
    background: "#0b1120"
    surface: "#0f172a"
    foreground: "#e5e7eb"
    border: "#1e293b"
typography:
  body:
    fontFamily: '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif'
  label:
    fontFamily: '"SF Mono", "Cascadia Code", Consolas, "Liberation Mono", monospace'
    fontSize: "0.6875rem"
    letterSpacing: "0.16em"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
  button-ghost:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
  section:
    borderTop: "{colors.border}"
    padding: "20px 0 0"
  entity-chip:
    rounded: "{rounded.sm}"
    padding: "1px 5px"
---

# Design System: Протокол

## Overview

**Creative North Star: "The Quiet Vault"**

Протокол is a private meeting transcriber. The person using it handles other people's personal data, so the interface must feel like a sealed, orderly vault — calm, exact, quietly authoritative. Restraint is the point: when the promise is "PII never leaves this machine," a surface that shouts undermines it.

The single most important decision is that the result is **a document, not a dashboard**. One column of continuous text, sections separated by hairline rules and small monospace labels — like minutes being read, not three floating cards with shields on them. The masking is shown inline, in the running text, so privacy is something you read rather than a panel you glance at.

**Key characteristics:**
- **Document, not cards.** Sections are separated by 1px rules and small mono labels; there are no bordered boxes, no shadows, no accent dots, no numbered titles.
- **Near-monochrome chrome, one accent.** `#1d4ed8` marks the single primary action, the progress fill, and the focus ring — nothing else.
- **Colour means PII.** The only saturated colour on screen is the entity chips; everything else is slate on white/paper.
- **Mono for the machine.** Tokens, counts, durations, model ids, timestamps — and the section labels themselves — are monospace. Prose is the system sans.
- **Marked and themable.** A brand mark (the app icon's bars-in-a-square) anchors the header, and the whole surface flips to a dark palette from one control.

## Colors

Near-monochrome slate-and-paper chrome, one disciplined accent, a saturated chip palette used only for masked entities.

### Dark theme
The same system on ink: page `#0b1120`, surface `#0f172a`, text `#e5e7eb`, hairline `#1e293b`; Vault Blue stays the accent and the chip palette darkens to keep its hue mapping legible. Applied by toggling a `.dark` class on `<html>`, before first paint, from a saved preference.

### Primary
- **Vault Blue** (`#1d4ed8`): the one accent — the primary button, the progress indicator fill, the focus ring. Its rarity is deliberate.

### Neutral
- **Ink** (`#0f172a`): primary text and the document title. Near-black, not black.
- **Paper** (`#f1f5f9`): the page surface; the document sits on white.
- **Slate text** (`#64748b`) and **faint** (`#94a3b8`): meta lines, section labels, timestamps.
- **Hairline** (`#e2e8f0`): every separator — section rules and control borders. Separation is done with lines, never with shadows or boxes.

### Destructive
- **Signal Red** (`#b91c1c`): error text only.

### Entity chips (the signature colour system)
Colour appears here and almost nowhere else — the tokens that got masked, so privacy is visible in the running text.
- **PERSON** — blue (`#dbeafe` / border `#93c5fd` / text `#1e3a8a`)
- **ADDRESS** — green (`#dcfce7` / `#86efac` / `#14532d`)
- **PHONE** — amber (`#fef3c7` / `#fcd34d` / `#78350f`)
- **EMAIL** — violet (`#ede9fe` / `#c4b5fd` / `#4c1d95`)
- **Documents** (PASSPORT / INN / SNILS / OMS / CARD / DRIVER_LICENSE / MILITARY_ID / BIRTH_CERTIFICATE) — red (`#fee2e2` / `#fca5a5` / `#7f1d1d`)
- **URL / IP** — slate (`#e2e8f0` / `#cbd5e1` / `#0f172a`)
- **OTHER** — quiet slate (`#f1f5f9` / `#cbd5e1` / `#334155`)

### Named rules
**The One Accent Rule.** `#1d4ed8` marks exactly one thing per view: the primary action, the live progress, or the focus ring.
**The Colour-Means-PII Rule.** Saturation signals "this is masked data." Anything coloured that is not an entity chip is a mistake. This is why the previous decorative accent dots, coloured metadata pills, and speaker hues were removed — meta text is mono slate, speaker labels are plain mono text.

## Typography

**Prose / chrome:** Segoe UI stack. **Labels & machine data:** SF Mono stack.

### Hierarchy
- **Document title** — the file name, `1.5rem` semibold, tight tracking. It is the page's only large text.
- **Section label** — mono, `0.6875rem`, uppercase, `0.16em` tracking, slate-500. Names the block ("ТРАНСКРИПТ", "ЧТО УХОДИТ В МОДЕЛЬ", "ОТВЕТ МОДЕЛИ").
- **Body** — `0.9375rem` / `1.75` line-height, slate-800, measure capped at `68ch`. Transcript, masked text and reply all read at this size.
- **Meta** — mono `0.75rem`, tabular numerals, slate-500: one line under the title (date · duration · ПДн · model), token counts, timestamps.

### Named rules
**The Mono-for-Machine Rule.** Anything the pipeline produced — token, count, duration, model id, timestamp — renders in mono. Prose never does. Section labels are mono too: the structure of a protocol is machine-made scaffolding around human text.

## Layout

A single centred shell capped at `max-w-5xl` (64rem). A `200px` history index sits at the left on wide screens, collapsing above the document below `lg`. The document column holds a reading measure of `68ch`; the remaining width is margin, which is intentional — a document has margins.

Sections stack top to bottom, each opened by `mt-8 border-t pt-5` (a hairline and a label). Nothing is floated or boxed. The order is fixed: transcript → masked text → model reply.

**The Order-Matches-Pipeline Rule.** Sections read in the order the data flows: what was said → what leaves for the model → what the model answered. Never rearrange.

## Elevation & Depth

Flat, and flatter than before: the single card shadow is gone. Depth and grouping come from hairline rules and the paper/page split alone. No shadows, no glass, no gradients.

**The Border-First Rule.** Separate with a 1px line. If a shadow appears anywhere, it is wrong.

## Shapes

Small and utilitarian: `6px` on controls, `4px` on chips, `8px` on the drop target and the two disclosure boxes. Rounded cards are gone; the document is a plane, not a stack of tiles.

## Components

### Brand mark
The app-bar identity: the icon's shape — two white bars in a rounded Vault Blue square — at `28px` beside the wordmark «Протокол» and the one-line descriptor. The same mark is the favicon and the desktop icon, so the product has one face.

### Document header
File name as the title (`1.5rem` semibold, wraps), one mono meta line beneath, then quiet actions: `Скачать .txt` and `Печать / PDF` (outlined) and `Обработать ещё` (text). No badge row, no accent dot.

### Onboarding (empty state)
The first run teaches the product, not just the drop zone: the brand mark, a value headline («Расшифровка встреч, которая не покидает ваш компьютер»), a one-line privacy promise, the three pipeline steps as mono labels (`01 · АУДИО  02 · МАСКИРОВАНИЕ  03 · ПРОТОКОЛ`), the primary CTA, and the accepted formats. One dashed target, now with a reason to trust it.

### Model reply
The protocol arrives from the model as Markdown. It is rendered, not dumped: `#`/`**bold**` lines become section subheadings, `- ` runs become bullet lists, `1.` runs become numbered lists, `| … |` + `|---|` becomes a real table, `> ` a quote, ```` ``` ```` a code block, `---` a hairline, and inline `**`/`*`/`` ` ``/`[..](..)` become strong/em/code/link. The raw Markdown markers never reach the page. The renderer is hand-rolled — a bounded GFM subset, no dependency — so the protocol keeps the document's own type instead of a library's defaults.

### Section
A hairline above, a mono uppercase label, an optional right-aligned meta (token count, "Скопировать"), then the content. This replaces the card.

### Entity chips (signature)
Mono, `0.8125rem`, `4px` radius, 1px border, saturated background with tone-on-tone text (see the palette). Stateless inline markers inside the running text.

### Speaker turns
When a recording has several speakers, the transcript becomes a list: a `92px` margin rail with the speaker label ("Спикер 1") and start time in mono slate, then the turn's text at the reading measure. Monochrome — identity is the number, not a hue.

### Buttons
- **Primary:** solid Vault Blue, white text, `min-h-9`, `6px 12px` — the single CTA ("Выбрать аудиофайл").
- **Ghost:** white, slate-800 text, 1px slate-300 border — secondary ("Скачать .txt", "Печать / PDF", "Настройки", theme toggle).
- **Text:** no border, slate-500 → slate-900 on hover — inline affordances ("Обработать ещё", "Скопировать").

### Inputs
Monochrome fields on white, 1px `--border`, `6px` radius, focus ring in Vault Blue.

### Progress
A thin `h-1.5` `bg-slate-200` track filled with the accent; a message on the left, a mono percentage on the right.

### Drop target
One large dashed zone, centred, doubled as the onboarding panel (see Onboarding). The old empty-state card is gone — there is exactly one dashed target, and it explains the product instead of only inviting a drop.

### Settings strip
A slate band under the header: the model field, the OpenRouter key status (emerald / amber by state), and a one-line note that the key lives in `.env`.

### History index
A plain list, not cards: a bordered `Поиск` field above it, each row the file name plus a mono `date · N ПДн`; the active row is blue on slate-100. On hover a `✎` renames the row in place (the name becomes an input; Enter commits, Escape cancels) and a `×` deletes it. An unmatched search reads «Ничего не найдено».

### Print
`Печать / PDF` drops all chrome — app bar, history, action rows, copy buttons (`no-print`) — and prints the document on `18mm` page margins. Export needs no extra dependency: the browser's own PDF printer is the exporter.

## Do's and Don'ts

### Do
- Separate sections with hairlines and mono labels; keep the document a single column.
- Spend colour only on entity chips; keep everything else slate on white/paper.
- Use mono for machine data and for section labels; keep prose in the sans face.
- Cap the reading measure at `68ch`.
- Keep one primary action per view.

### Don't
- Don't decorate with accent dots, numbered titles, or coloured metadata pills — all three were removed on purpose.
- Don't float content in bordered cards with headers; that reads as a dashboard, not a protocol.
- Don't colour anything that isn't a masked entity.
- Don't put prose in mono or machine tokens in the sans face.
- Don't let the document overflow — at 375px it stacks to one column with zero horizontal scroll.
