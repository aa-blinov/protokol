---
name: Protokol
description: A private meeting transcriber. Warm paper and ink, one ledger green accent, and colour reserved for the entities the app masks.
colors:
  primary: "#1f5a46"
  primary-foreground: "#ffffff"
  foreground: "#1d1b16"
  background: "#ece7dc"
  sheet: "#faf8f3"
  paper: "#efebe3"
  muted-foreground: "#6b6556"
  border: "#e3ded3"
  destructive: "#b91c1c"
  dark:
    background: "#12110e"
    sheet: "#1a1915"
    foreground: "#ece8dc"
    border: "#33312a"
typography:
  body:
    fontFamily: '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: "28px"
  label:
    fontFamily: '"SF Mono", "Cascadia Code", Consolas, "Liberation Mono", monospace'
    fontSize: "12px"
    letterSpacing: "0.12em"
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
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
    rounded: "6px"
    padding: "0 12px"
  button-ghost:
    backgroundColor: "{colors.sheet}"
    textColor: "#2f2b23"
    rounded: "6px"
    padding: "0 12px"
  section:
    borderTop: "{colors.border}"
    padding: "20px 0 0"
  entity-chip:
    rounded: "4px"
    padding: "1px 6px"
---

# Design system: Protokol

## Overview
**Creative North Star: "The quiet vault"**

Protokol is a private meeting transcriber. The person using it handles other
people's personal data, so the interface has to feel like a sealed, orderly
vault: calm, exact, quietly authoritative. Restraint is the point. When the
promise is "the personal data never leaves this machine", a surface that
shouts undermines it.

The most important decision is that the result is a document, not a
dashboard. One column of continuous text, sections separated by hairline
rules and small monospace labels, like minutes being read rather than three
floating cards with shields on them.

The visual world is the interface kit shipped with Monos: one monospaced
voice, a 6px corner, hairline borders, and colour that only ever means
something. The page keeps its composition; what changed underneath it is the
palette, the face and the shape of every control.

Key characteristics:

- **Document, not cards.** Sections are separated by a 1px rule and a small
  mono label. There are no bordered boxes, no shadows, no accent dots and no
  numbered titles.
- **One voice.** Everything is set in JetBrains Mono: the transcript, the
  labels, the numbers, the buttons. A protocol is a machine-made artefact with
  human text inside it, and the single face says so.
- **Dark by default.** The app opens in the dark half of the palette. The light
  half is for daylight and for printing.
- **No filled action button.** The word is the button: small caps, wide
  tracking, weight instead of a slab of colour. The only frame on a screen
  belongs to the chosen state of a toggle.
- **Colour means personal data.** The only saturated colour on screen is the
  entity chips; everything else is warm grey.
- **Marked.** The brand mark is a redacted page drawn in ink, and the whole
  surface flips between the two halves from one control.

The interface language is Russian. The name on screen is "Протокол".

## Colors
Gruvbox, both halves. The neutrals are warm on purpose: a page of text reads as
paper under a lamp rather than as a screen.

| Token | Dark (default) | Light | Used for |
| --- | --- | --- | --- |
| `paper` | `#282828` | `#fbf1c7` | the page |
| `sheet` | `#3c3836` | `#f2e5bc` | the app bar, fields, raised surfaces |
| `ink` | `#ebdbb2` | `#3c3836` | body text, headings |
| `stone-500` | `#a89984` | `#6a5e53` | meta, labels, secondary text |
| `stone-200` | `#504945` | `#d5c4a1` | the hairline |
| `accent-700` | `#83a598` | `#3d7375` | the one action, links, focus ring |

Every pair used for text clears 4.5:1 in both halves. `stone-400` and the light
`accent-700` were raised to reach it; the values above are the measured ones,
not the palette's raw ones.

**The Colour Means Something Rule.** Red, amber and olive exist only inside the
entity chips, where they name the kind of personal data. Nothing else on the
page is allowed to be saturated.

### Entity chips

A chip is a bordered word on the canvas, not a filled block: 6px corner, a 1px
border in the tone, the same tone as the text, and the page's own ground. Six
groups share five tones and a neutral. The chip is the only place on screen
where a colour other than the accent appears, and it reads as a label rather
than as a highlight.

## Typography
One face, everywhere: **JetBrains Mono**, bundled in `src/fonts` as three
weights and served from the page. It is not fetched from a CDN: the app runs
offline in a desktop window, and a hosted stylesheet would be a network
dependency at first paint.

### Hierarchy

- **Document title**: the file name, `text-2xl` at 24px, semibold, tight
  tracking. It is the only large text on the page.
- **Wordmark**: the product name in the app bar, `text-lg` at 18px, semibold.
- **Section label**: 12px, uppercase, `0.12em` of tracking, in stone. It names
  the block: "ВЫЖИМКА", "РАСШИФРОВКА".
- **Body**: 15px with a line height of 28px, in stone 800, capped at `68ch`.
- **Meta**: 12px in stone 500, with tabular numerals for the counts and the
  timestamps.
- **Action**: 14px uppercase, `0.1em` of tracking, semibold for the primary and
  regular for the quiet one.

### Named rules

**The One Voice Rule.** The transcript is mono. A protocol is read for what was
said and for what was decided, and the numbers, the tokens and the names sit in
the same column as the sentences; a second face would break the column.

## Layout

A single centred shell capped at `max-w-5xl`, which is 64rem. A rail of
`200px` sits at the left on the wide screens and falls under the document
below `lg`. The document column holds a reading measure of `68ch`, and the
width that is left over is margin, on purpose: a document has margins.

The sections stack from top to bottom, each one opened by `mt-8 border-t
pt-5`, a hairline and a label. Nothing is floated and nothing is boxed. The
order is fixed: the transcript, then the masked text, then the reply of the
model.

**The Order Matches the Pipeline Rule.** The sections read in the order the
data flows: what was said, what leaves for the model, what the model
answered. They are never rearranged.

## Elevation & Depth

Flat, and flatter than it was: the single card shadow is gone. The depth and
the grouping come from the hairline rules and from the paper and sheet
split alone. There are no shadows, no glass and no gradients.

**The Border First Rule.** Separate with a 1px line. A shadow anywhere is
wrong.

## Shapes
Small and utilitarian. One token, `--radius: 6px`, and every corner on the page
derives from it: fields, chips, buttons, the empty-state frame. There is no
larger radius anywhere.

**The One Corner Rule.** If a corner is not 6px, it is a circle: a status dot,
nothing else.

## Components

### The brand mark
The app bar identity: a page with three lines, drawn as line art in the current
ink, no fill, inside the same 32 × 32 box the icon used. It replaces the old
green tile, because the system has no filled brand block: the mark is drawn the
way every other border on the page is. It is the app icon and the favicon as
well, so the product has one face.

### The document header
The file name as the title at 24px, one meta line beneath it, and then quiet
actions: "Скачать .txt", "Печать / PDF" and "Развернуть всё", all as words.
There is no badge row and no accent dot.

### The empty state

The first run teaches the product and not only the drop zone: the brand
mark, a plain action headline, "Загрузите запись встречи", the primary call
to action at 48 pixels, the accepted formats, and one closing line that
states the new default, that the reader will see what is sent and what it
costs before deciding. One dashed target, and it has a reason to trust it.

### The pre-send review

The screen between "the audio is transcribed" and "anything is sent". It
exists because the privacy claim is worth something only if it can be
inspected.

- A status band with a shield: "расшифровка готова, пока ничего не
  отправлено", and the count of what was hidden.
- The complete masked text, in the entity chips, inside a scrollable well
  26rem high. The point is that it is the entire outgoing text and not a
  sample. Past 3000 characters it opens truncated, with "Показать целиком".
- The focus as three radio rows at `min-h-11`, with a filled circle when one
  is chosen, the extra requirement when there is one, and then the pre-flight
  cost: the tokens, the number of requests when the recording is long enough
  to be split, and the money.
- One primary action, "Составить выжимку", and one text escape, "Оставить
  только расшифровку". A transcript with no summary is a legitimate outcome
  and not a failure.

The cost line sits under the focus and not in the header: what is being paid
for is this particular summary, so the number belongs to the choice.

### Running the summary again

Under a finished summary, "Составить заново" opens a bordered panel that
says in the first line that the transcript is not recomputed, then the same
focus radios and the same estimate. Without that line a second summary reads
as a second full run, and the cost beside the button looks as if it covers
both. After the call the document replaces the estimate with the exact
figure from the token counts of the provider.

### The transcript search

The search sits above the transcript and not in the history rail, because the
rail filters the recordings and this filters one of them. The matches are
amber and the current one gets an outline, so that it stays findable in a
transcript that is several screens long. There is an "N из M" counter and
two step buttons, and Enter and Shift+Enter work from anywhere on the page.
Typing a query lifts the long-transcript cap on its own, because a search
that reported hits below the fold would be lying. The count is capped at
2000 hits, with a note to narrow the query, because a one-letter query in an
hour of speech would otherwise paint tens of thousands of spans.

An entity chip and a search hit can overlap, because someone looking for a
name is searching for text that the app also marks as personal data. The
renderer cuts the text at every boundary that both introduce and labels each
run, so that neither wins and the chip is never lost.

### The reply of the model

The protocol arrives as Markdown and is rendered rather than dumped. A `#`
line and a `**bold**` line become section subheadings, a `- ` run becomes a
bullet list, a `1.` run becomes a numbered list, a `| ... |` row with a
`|---|` row becomes a real table, a `> ` becomes a quote, a fenced block
becomes a code block, `---` becomes a hairline, and the inline `**`, `*`,
`` ` `` and `[..](..)` become strong, em, code and link. The raw Markdown
markers never reach the page.

The renderer is hand-rolled, a bounded subset of GFM with no dependency, so
that the protocol keeps the type of the document instead of the defaults of a
library.

### The section

A hairline above, a mono uppercase label, an optional right-aligned meta
line, and then the content. This replaces the card.

The meta slot holds section-scoped controls only, such as "Скопировать" and
"Показать целиком". A mono uppercase label with a 45-character figure beside
it reads as noise, and every purpose that lands here multiplies that noise
by the number of sections. The facts about the call, the cost and the token
counts, belong with the control that would spend again, which is the
"Составить заново" line. The facts about the text belong in the text.

### Say it once

The privacy promise appeared four times, in the empty state, the review
band, the document placeholder and the export header, and by the third time
it was decoration. Each claim now has one home, chosen by when it becomes
true: the empty state says what happens next, the review band says what was
hidden and where to read it, and the document shows the masked copy instead
of describing it.

The numbers follow the same rule. The review screen used to print "5 личных
данных" in the meta line and "Скрыто 5 значений" fifty pixels below. The
meta line now carries what the band does not, the duration and the speaker
count, in mono, because the pipeline produced them.

### Space before weight

"Скачать .txt", "Печать / PDF" and "Обработать ещё" were three identical
ghost buttons in one row, which made the one button worth pressing look
like the two nobody presses. The exports stay next to each other and the
loop moves to the far edge as a text button. Separating them with space
costs nothing, and the quiet world does not need another colour to say
"primary".

### The accent is not blue-700

`#1f5a46` is the one accent, and the interface used to say `bg-blue-700` in
fourteen places. Those are not the same colour: shadcn rewrites the whole
`--color-blue-*` scale to its own indigo, so every one of those fourteen
resolved to an indigo around `#4338ca` while the token file named
`#1f5a46`. The palette was right on paper and wrong on screen, and nothing
errored.

Two consequences, both enforced now:

- The five shades the interface uses are restated in `:root`: `50`, `300`,
  `700`, `800` and `900`. Restating the one scale beats hunting for every
  offending class.
- The button wrapper passes the library a variant with no background of its
  own. The wrapper's `bg-blue-700` and the library's `bg-primary` both
  applied to the same button, and the library won on cascade order.

### The browser surfaces

The selection, the scrollbars, the underline offset and the caret are drawn
by the browser and not by the app, and they arrive in the system blue, the
one place on screen where a colour nobody chose appears. All four are
themed.

The selection tints the background and leaves the ink dark rather than the
reverse, so that the copied text stays readable whichever way the reader
swipes. The underlines get `0.18em` of offset, because at the default the
line crosses the descenders of "ц" and "й", which in this typeface reads as
a strike.

### Forced colours

In the high contrast mode of Windows the author colours are discarded. The
focus ring survives, because it is an outline, but the selected preset
loses its fill and a tinted status band loses its background, and in both
cases one weak signal is left. Both are stated explicitly under
`forced-colors: active`.

### The entity chips

Mono, `0.8125rem`, a 4px radius, a 1px border, a saturated background and
a tone-on-tone text. They are stateless inline markers inside the running
text.

### The speaker turns

When a recording has several speakers the transcript becomes a list: a
`92px` margin rail with the speaker label, "Спикер 1", and the start time in
mono stone, and then the text of the turn at the reading measure. It is
monochrome, because the identity is the number and not a hue.

### The buttons

- **Primary**: solid ledger green with white text, `min-h-9` and `px-3`,
  or `min-h-12` and `px-6` at the large size, with a 6px radius. The
  single call to action.
- **Ghost**: the sheet colour with a stone 300 border and stone 800 text.
  The secondary actions: "Скачать .txt", "Печать / PDF", "Настройки" and the
  theme toggle.
- **Text**: no border, stone 500 that turns stone 900 on hover. The inline
  affordances: "Обработать ещё" and "Скопировать".

### The fields

Monochrome fields on the sheet colour, with a 1px stone 300 border, a 6px
radius and a focus ring in ledger green. The padding and the radius are one
constant, `FIELD`, so that the settings panel cannot drift into three
heights and two border shades.

### The progress

A thin track one pixel band high in the muted colour, filled with the
accent. The message is on the left and a mono percentage is on the right.

### The drop target

One large dashed zone, centred, which doubles as the onboarding panel. The
old empty-state card is gone: there is exactly one dashed target, and it
explains the product instead of only inviting a drop.

### The history index

A plain list and not a set of cards: a bordered search field above it, and
each row is the file name with a mono line under it that reads "выжимка · N
персональных данных", or "без выжимки", which answers "does this one have
the answer or only the text" before it is opened. The active row is blue on
stone 100. On hover a pencil renames the row in place, so the name becomes
an input where Enter commits and Escape cancels, and a trash icon deletes
it, in two steps, because a removed transcript cannot be brought back. A
search that matches nothing reads "Ничего не нашлось".

### The settings panel

The settings live in the left rail, behind a single row that reads
"Настройки". It opens as a view in place of the document, and "К записям"
goes back, so the settings never float over the transcript they describe.

### The print

"Печать / PDF" drops all the chrome, the app bar, the history, the action
rows and the copy buttons, and prints the document on 18mm page margins.
The export needs no extra dependency, because the browser's own PDF printer
is the exporter.

## Do's and Don'ts

### Do:

- **Do** separate the sections with hairlines and mono labels, and keep the
  document a single column.
- **Do** spend colour only on the entity chips, and keep everything else
  stone on white or paper.
- **Do** set everything in JetBrains Mono, and let the hierarchy come from
  size and weight.
- **Do** cap the reading measure at `68ch`.
- **Do** keep one primary action per view.
- **Do** state each promise once, in the place where it becomes true.

### Don't:

- **Don't** decorate with accent dots, numbered titles or coloured
  metadata pills. All three were removed on purpose.
- **Don't** float the content in bordered cards with headers. That reads as
  a dashboard, not as a protocol.
- **Don't** colour anything that is not a masked entity, and never fill a
  chip with it.
- **Don't** introduce a second face, or a filled action button. The word is
  the button.
- **Don't** let the document overflow. At 375px it stacks into one column
  with no horizontal scroll.
- **Don't** put a shadow anywhere. The rule above is not a preference.
