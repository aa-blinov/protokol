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
        {meta ? <div className="text-xs text-slate-500">{meta}</div> : null}
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
