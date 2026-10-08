/** App-level design primitives, layered on the shadcn/ui components.
 *
 *  The library supplies structure and behaviour — ARIA on Progress, focus and
 *  disabled handling on Button — while the overrides below keep the app's own
 *  slate/blue identity, which the README screenshots document. `cn` is
 *  tailwind-merge, so a later className wins over the library's defaults.
 *
 *  Public API is stable; App.tsx is the only consumer. */

import type { ReactNode } from "react";
import {
  Card as CardSurface,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge as BadgeSurface } from "@/components/ui/badge";
import { Button as ButtonSurface } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

export function Card({
  title,
  meta,
  children,
  accent,
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  accent?: string;
}) {
  return (
    <CardSurface className="gap-0 rounded-lg border border-slate-200 bg-white py-0 shadow-sm ring-0">
      <CardHeader className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          {accent ? (
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: accent }} />
          ) : null}
          {title}
        </CardTitle>
        {meta ? <CardAction className="self-center text-xs text-slate-500">{meta}</CardAction> : null}
      </CardHeader>
      <CardContent className="px-4 py-3">{children}</CardContent>
    </CardSurface>
  );
}

const TONES = {
  slate: "border-slate-200 bg-slate-100 text-slate-700",
  green: "border-emerald-200 bg-emerald-50 text-emerald-800",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  red: "border-red-200 bg-red-50 text-red-800",
  blue: "border-blue-200 bg-blue-50 text-blue-900",
} as const;

type Tone = keyof typeof TONES;

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: Tone }) {
  return (
    <BadgeSurface variant="outline" className={`rounded-full px-2 py-0.5 ${TONES[tone]}`}>
      {children}
    </BadgeSurface>
  );
}

// The app's "ghost" is an outlined secondary button, not a bare one — it maps to
// shadcn's "outline" rather than its "ghost".
const BUTTON_SURFACE = {
  primary: "bg-blue-700 text-white hover:bg-blue-800 hover:text-white",
  ghost: "border-slate-300 bg-white text-slate-800 hover:bg-slate-50 hover:text-slate-800",
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
      variant={variant === "primary" ? "default" : "outline"}
      className={`min-h-11 px-4 ${BUTTON_SURFACE[variant]}`}
    >
      {children}
    </ButtonSurface>
  );
}

export function ProgressBar({ pct, message }: { pct: number; message: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs text-slate-600">
        <span>{message}</span>
        <span className="font-mono tabular-nums text-slate-500">{pct}%</span>
      </div>
      <Progress value={pct} aria-label={message} className="h-2 rounded-full bg-slate-200" />
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white/60 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-800">{title}</p>
      <p className="mt-1 text-sm text-slate-500">{hint}</p>
    </div>
  );
}
