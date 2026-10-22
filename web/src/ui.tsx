/** App-level primitives for the protocol surface.
 *
 *  Deliberately not a card kit: the result reads as a document, so sections are
 *  separated by hairline rules and small monospace labels rather than floated,
 *  bordered cards. The library still supplies Button/Progress behaviour. */

import { type ReactNode, useState } from "react";
import { Button as ButtonSurface } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { ChevronDown } from "lucide-react";

// The kit has no filled action button: the word is the button. Emphasis comes
// from weight and small caps, not from a slab of colour, so a page has exactly
// one visual temperature no matter how many actions sit on it.
const BUTTON_SURFACE = {
  primary:
    "text-accent-700 font-bold uppercase tracking-widest hover:opacity-70 active:opacity-60",
  ghost:
    "text-stone-700 font-normal uppercase tracking-widest hover:text-stone-900",
  text: "text-stone-500 font-medium hover:text-stone-900",
} as const;

/** Border, padding and radius for every single-line field.
 *
 *  These used to be spelled out at each site and had drifted to three heights
 *  and two border shades. Nobody names that, everybody sees it -- a settings
 *  panel whose fields do not line up reads as unfinished even when each field
 *  is correct on its own. `check_controls.py` fails the build if it drifts
 *  again. Add `pl-`/`pr-` after this for an inset icon; Tailwind emits those
 *  later, so they win. */
export const FIELD =
  "rounded border border-stone-300 bg-sheet px-3 py-2 leading-5 transition-colors focus:border-stone-400 focus:outline-none";

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
  ariaLabel,
  ariaExpanded,
  size = "md",
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: keyof typeof BUTTON_SURFACE;
  type?: "button" | "submit";
  ariaLabel?: string;
  ariaExpanded?: boolean;
  /** For placement only — layout a button should not have to carry. */
  className?: string;
  /** "lg" is for the one action a screen exists for. Everything else stays
   *  at the 36 px default, which is right for a toolbar and small for a tap. */
  size?: "md" | "lg";
}) {
  return (
    <ButtonSurface
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-expanded={ariaExpanded}
      variant="bare"
      className={`rounded-[6px] ${size === "lg" ? "min-h-11 px-5 text-sm" : "min-h-9 px-3 text-sm"} ${BUTTON_SURFACE[variant]} ${className ?? ""}`}
    >
      {children}
    </ButtonSurface>
  );
}

/** A document section: small mono label, optional right-hand meta, hairline above.
 *  With `onToggle` the label folds the body away and `collapsedNote` stands in for
 *  it, so a long document can be skimmed section by section. */
export function Section({
  label,
  meta,
  collapsedNote,
  collapsed = false,
  onToggle,
  children,
}: {
  label: string;
  meta?: ReactNode;
  /** Shown instead of the body when collapsed, so the reader can tell what is
   *  in there without opening it. */
  collapsedNote?: string;
  collapsed?: boolean;
  onToggle?: () => void;
  children: ReactNode;
}) {
  // The label itself is the trigger, not a small link in the corner: a
  // disclosure is a label that opens things, and a 12px «скрыть» on the right
  // reads as another action competing with the ones beside it.
  //
  // The button covers the heading only and `meta` stays a sibling. Wrapping the
  // whole row put the section's «Скопировать» inside another button — invalid
  // HTML, and the click that copied the text also folded the section.
  const LABEL = "font-mono text-[12px] font-medium uppercase tracking-[0.12em]";
  const heading = onToggle ? (
    <h3>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className={`focus-ring flex cursor-pointer items-baseline gap-1.5 rounded ${LABEL} text-stone-500 hover:text-stone-900`}
      >
        <ChevronDown
          aria-hidden
          className={`h-3.5 w-3.5 shrink-0 transition-transform ${collapsed ? "-rotate-90" : ""}`}
        />
        {label}
        <span className="sr-only">, {collapsed ? "развернуть" : "свернуть"}</span>
      </button>
    </h3>
  ) : (
    <h3 className={`${LABEL} text-stone-500`}>{label}</h3>
  );

  return (
    <section className="mt-8 border-t border-stone-200 pt-5">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        {heading}
        {meta ? <div className="no-print text-xs text-stone-500">{meta}</div> : null}
      </div>
      {collapsed ? (
        collapsedNote ? (
          <p className="text-xs text-stone-500">{collapsedNote}</p>
        ) : null
      ) : (
        children
      )}
    </section>
  );
}

export function CopyButton({ text, label = "Скопировать" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => {});
      }}
      className="focus-ring rounded text-xs text-stone-500 transition-colors hover:text-stone-900"
    >
      {copied ? "Скопировано" : label}
    </button>
  );
}

// The model answers in Markdown, so the renderer covers the constructs a
// protocol actually uses: headings, bullet and numbered lists, tables, code,
// quotes, rules, and inline emphasis/link/code. Hand-rolled to keep the app
// dependency-free and to keep control of the document's own typography.
const INLINE =
  /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(_[^_\n]+_)|(~~[^~]+~~)|(\[[^\]]+\]\([^)\s]+\))/g;

const TEXT = "text-[15px] leading-7 text-stone-800";

/** Inline spans: code, bold, italic, strikethrough, links. */
function renderInline(text: string): ReactNode {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  INLINE.lastIndex = 0;
  let match: RegExpExecArray | null = INLINE.exec(text);
  while (match !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(
        <code key={key++} className="rounded bg-stone-100 px-1 py-0.5 font-mono text-[0.85em] text-stone-700">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(
        <strong key={key++} className="font-semibold text-stone-900">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("~~")) {
      nodes.push(<del key={key++}>{token.slice(2, -2)}</del>);
    } else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      nodes.push(
        <a
          key={key++}
          href={link ? link[2] : "#"}
          target="_blank"
          rel="noreferrer"
          className="text-accent-700 underline decoration-stone-300 underline-offset-2"
        >
          {link ? link[1] : token}
        </a>,
      );
    } else {
      nodes.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
    last = match.index + token.length;
    match = INLINE.exec(text);
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function parseRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  return value.split("|").map((cell) => cell.trim());
}

const isTableSeparator = (line: string): boolean =>
  line.includes("-") && /^\s*\|?[\s:|-]+\|?\s*$/.test(line) && !/[^\s:|-]/.test(line);

/** Renders the model's Markdown as the document's own typography. */
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  const paragraph: string[] = [];
  let i = 0;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push(
      <p key={`p${i}`} className={`mt-2 max-w-[68ch] ${TEXT}`}>
        {renderInline(paragraph.join(" "))}
      </p>,
    );
    paragraph.length = 0;
  };

  const takeWhile = (test: (line: string) => RegExpExecArray | null, items: string[]) => {
    while (i < lines.length) {
      const match = test(lines[i].trim());
      if (!match) break;
      items.push(match[1]);
      i++;
    }
  };

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trim();

    if (line === "") {
      flushParagraph();
      i++;
      continue;
    }

    if (/^```/.test(line)) {
      flushParagraph();
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        code.push(lines[i]);
        i++;
      }
      i++;
      blocks.push(
        <pre
          key={`c${i}`}
          className="mt-2 max-w-[68ch] overflow-x-auto rounded border border-stone-200 bg-stone-50 p-3 font-mono text-[13px] leading-6 text-stone-700"
        >
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flushParagraph();
      const header = parseRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().includes("|") && lines[i].trim() !== "") {
        rows.push(parseRow(lines[i]));
        i++;
      }
      blocks.push(
        <div key={`t${i}`} className="mt-3 max-w-[68ch] overflow-x-auto">
          <table className={`w-full border-collapse ${TEXT}`}>
            <thead>
              <tr>
                {header.map((cell, column) => (
                  <th
                    key={column}
                    className="border-b border-stone-200 px-2 py-1 text-left font-semibold text-stone-900"
                  >
                    {renderInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, column) => (
                    <td key={column} className="border-b border-stone-100 px-2 py-1 align-top">
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line) ?? /^\*\*(.+?)\*\*:?$/.exec(line);
    if (heading) {
      flushParagraph();
      blocks.push(
        <h4 key={`h${i}`} className="mt-5 font-semibold tracking-tight text-stone-900">
          {renderInline(heading[2] ?? heading[1])}
        </h4>,
      );
      i++;
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flushParagraph();
      blocks.push(<hr key={`r${i}`} className="my-5 border-t border-stone-200" />);
      i++;
      continue;
    }

    if (/^>\s?/.test(line)) {
      flushParagraph();
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
        quote.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote key={`q${i}`} className="mt-2 max-w-[68ch] border-l border-stone-300 pl-4 text-stone-600">
          {renderInline(quote.join(" "))}
        </blockquote>,
      );
      continue;
    }

    const ordered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      flushParagraph();
      const items = [ordered[1]];
      i++;
      takeWhile((item) => /^\d+[.)]\s+(.*)$/.exec(item), items);
      blocks.push(
        <ol key={`o${i}`} className={`ml-5 mt-2 list-decimal space-y-1 ${TEXT}`}>
          {items.map((item, index) => (
            <li key={index}>{renderInline(item)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    const bullet = /^[-*•+]\s+(.*)$/.exec(line);
    if (bullet) {
      flushParagraph();
      const items = [bullet[1]];
      i++;
      takeWhile((item) => /^[-*•+]\s+(.*)$/.exec(item), items);
      blocks.push(
        <ul key={`u${i}`} className={`ml-5 mt-2 list-disc space-y-1 ${TEXT}`}>
          {items.map((item, index) => (
            <li key={index}>{renderInline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    paragraph.push(line);
    i++;
  }
  flushParagraph();
  return <div>{blocks}</div>;
}

export function ProgressBar({
  pct,
  message,
  eta,
  elapsed,
}: {
  pct: number;
  message: string;
  /** Seconds left in this stage, from how long it took last time. Null on the
   *  first recording of a session, when nothing has been measured yet. */
  eta?: number | null;
  /** Seconds since the work started. Always known, unlike eta. */
  elapsed?: number;
}) {
  return (
    // Full width, deliberately: the bar sat at max-w-md, 448px against a drop
    // zone nearly twice that, and a progress indicator that stops two-thirds
    // across the area it is measuring looks like it is stuck.
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3 text-xs text-stone-600">
        {/* Only the stage message is a live region. Announcing the percentage
            on every tick would talk over the screen reader for a minute. */}
        <span role="status">{message}</span>
        <span className="flex shrink-0 items-baseline gap-2">
          {/* One time figure, and only one we can stand behind. A previous
              measurement gives a remainder; without one, elapsed time is the
              honest answer -- showing nothing for the first minute reads as a
              hang. */}
          {eta !== null && eta !== undefined && eta > 0 ? (
            <span className="text-stone-500">осталось примерно {humanSeconds(eta)}</span>
          ) : elapsed ? (
            <span className="text-stone-500">прошло {humanSeconds(elapsed)}</span>
          ) : null}
          <span className="font-mono tabular-nums text-stone-500">{pct}%</span>
        </span>
      </div>
      <Progress value={pct} aria-label={message} className="h-1.5 rounded-full bg-stone-300" />
    </div>
  );
}

/** "12 с", "1 мин 10 с" -- short enough for a progress line. */
function humanSeconds(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} с`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m < 60) return s ? `${m} мин ${s} с` : `${m} мин`;
  return `${Math.floor(m / 60)} ч ${m % 60} мин`;
}
