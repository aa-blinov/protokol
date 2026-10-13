/** App-level primitives for the protocol surface.
 *
 *  Deliberately not a card kit: the result reads as a document, so sections are
 *  separated by hairline rules and small monospace labels rather than floated,
 *  bordered cards. The library still supplies Button/Progress behaviour. */

import { type ReactNode, useState } from "react";
import { Button as ButtonSurface } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

const BUTTON_SURFACE = {
  primary: "bg-blue-700 text-white hover:bg-blue-800 hover:text-white",
  ghost: "border-slate-300 bg-white text-slate-800 hover:bg-slate-50 hover:text-slate-800",
  text: "text-slate-500 hover:bg-transparent hover:text-slate-900",
} as const;

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
      className={`rounded-[6px] ${size === "lg" ? "min-h-12 px-6 text-base" : "min-h-9 px-3"} ${BUTTON_SURFACE[variant]} ${className ?? ""}`}
    >
      {children}
    </ButtonSurface>
  );
}

/** A document section: small mono label, optional right-hand meta, hairline above. */
export function Section({ label, meta, children }: { label: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-8 border-t border-slate-200 pt-5">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h3 className="font-mono text-[12px] font-medium uppercase tracking-[0.12em] text-slate-500">{label}</h3>
        {meta ? <div className="no-print text-xs text-slate-500">{meta}</div> : null}
      </div>
      {children}
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
      className="focus-ring rounded text-xs text-slate-500 transition-colors hover:text-slate-900"
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

const TEXT = "text-[15px] leading-7 text-slate-800";

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
        <code key={key++} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] text-slate-700">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(
        <strong key={key++} className="font-semibold text-slate-900">
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
          className="text-blue-700 underline decoration-slate-300 underline-offset-2"
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
          className="mt-2 max-w-[68ch] overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3 font-mono text-[13px] leading-6 text-slate-700"
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
                    className="border-b border-slate-200 px-2 py-1 text-left font-semibold text-slate-900"
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
                    <td key={column} className="border-b border-slate-100 px-2 py-1 align-top">
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
        <h4 key={`h${i}`} className="mt-5 font-semibold tracking-tight text-slate-900">
          {renderInline(heading[2] ?? heading[1])}
        </h4>,
      );
      i++;
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flushParagraph();
      blocks.push(<hr key={`r${i}`} className="my-5 border-t border-slate-200" />);
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
        <blockquote key={`q${i}`} className="mt-2 max-w-[68ch] border-l-2 border-slate-300 pl-4 text-slate-600">
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
      <div className="flex items-baseline justify-between gap-3 text-xs text-slate-600">
        <span>{message}</span>
        <span className="flex shrink-0 items-baseline gap-2">
          {/* One time figure, and only one we can stand behind. A previous
              measurement gives a remainder; without one, elapsed time is the
              honest answer -- showing nothing for the first minute reads as a
              hang. */}
          {eta !== null && eta !== undefined && eta > 0 ? (
            <span className="text-slate-500">осталось примерно {humanSeconds(eta)}</span>
          ) : elapsed ? (
            <span className="text-slate-500">прошло {humanSeconds(elapsed)}</span>
          ) : null}
          <span className="font-mono tabular-nums text-slate-500">{pct}%</span>
        </span>
      </div>
      <Progress value={pct} aria-label={message} className="h-1.5 rounded-full bg-slate-200" />
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
