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
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: keyof typeof BUTTON_SURFACE;
  type?: "button" | "submit";
  ariaLabel?: string;
  ariaExpanded?: boolean;
}) {
  return (
    <ButtonSurface
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-expanded={ariaExpanded}
      variant={variant === "primary" ? "default" : "ghost"}
      className={`min-h-9 px-3 ${BUTTON_SURFACE[variant]}`}
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
        <h3 className="font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-slate-500">{label}</h3>
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

/** Inline emphasis for the model's light Markdown. */
function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*|\*(.+?)\*/g;
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null = pattern.exec(text);
  while (match !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    if (match[1] !== undefined) {
      nodes.push(
        <strong key={key++} className="font-semibold text-slate-900">
          {match[1]}
        </strong>,
      );
    } else {
      nodes.push(<em key={key++}>{match[2]}</em>);
    }
    last = match.index + match[0].length;
    match = pattern.exec(text);
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/** The protocol arrives as light Markdown; render it as document text rather
 *  than showing the model's `**` and `-` markers verbatim. */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length === 0) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="ml-4 mt-2 list-disc space-y-1 text-[15px] leading-7 text-slate-800">
        {list.map((item, index) => (
          <li key={index}>{inline(item)}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .forEach((raw, index) => {
      const line = raw.trim();
      if (line === "") {
        flush();
        return;
      }
      const bullet = /^[-*•]\s+(.*)$/.exec(line);
      if (bullet) {
        list.push(bullet[1]);
        return;
      }
      flush();
      if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) {
        blocks.push(<hr key={`hr-${index}`} className="my-5 border-t border-slate-200" />);
        return;
      }
      const heading = /^(#{1,6})\s+(.*)$/.exec(line) ?? /^\*\*(.+?)\*\*:?$/.exec(line);
      if (heading) {
        blocks.push(
          <h4 key={`h-${index}`} className="mt-5 font-semibold tracking-tight text-slate-900">
            {inline(heading[2] ?? heading[1])}
          </h4>,
        );
        return;
      }
      blocks.push(
        <p key={`p-${index}`} className="mt-2 max-w-[68ch] text-[15px] leading-7 text-slate-800">
          {inline(line)}
        </p>,
      );
    });
  flush();
  return <div>{blocks}</div>;
}

export function ProgressBar({ pct, message }: { pct: number; message: string }) {
  return (
    <div className="max-w-md space-y-2">
      <div className="flex items-baseline justify-between text-xs text-slate-600">
        <span>{message}</span>
        <span className="font-mono tabular-nums text-slate-500">{pct}%</span>
      </div>
      <Progress value={pct} aria-label={message} className="h-1.5 rounded-full bg-slate-200" />
    </div>
  );
}
