/** Controls shared by the pre-send check and the "re-do the summary" panel.
 *
 *  Both screens answer the same question -- what will be sent, and what will it
 *  cost -- so both build it from these pieces. The estimate is shown *before*
 *  the call because a provider call is billed and the user should be able to
 *  stop here; the exact figure replaces it afterwards. */

import { useEffect, useState } from "react";
import { estimateCost, type EstimateResult, type SettingsState } from "./api";

/** Duration the way a person says it: "4 мин 07 с", "1 ч 12 мин", "47 с".
 *  Raw seconds with a decimal ("4523.4 с") is machine output, not a reading. */
export function humanDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h} ч ${String(m).padStart(2, "0")} мин`;
  if (m) return `${m} мин ${String(s).padStart(2, "0")} с`;
  return `${s} с`;
}

/** Money at the scale these numbers actually are.
 *
 *  A 20-minute meeting costs fractions of a cent, so two decimals would print
 *  "0.00" and tell the user nothing. Below a cent the fourth significant digit
 *  is what makes it readable; above it, cents are enough. */
export function formatMoney(value: number | null): string {
  if (value === null) return "";
  if (value === 0) return "0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

/** "≈ 8 200 символов" -- thousands separated with a space, as in Russian. */
export function formatCount(value: number): string {
  return value.toLocaleString("ru-RU");
}

/** Russian needs three forms and a hard case besides: 1, 2, 4 take one, but
 *  11–14 take the plural even though they end in 1–4. Intl.PluralRules knows
 *  that and a hand-written n % 10 does not -- "11 токенов" is wrong. */
export function pluralRu(n: number, one: string, few: string, many: string): string {
  const rule = new Intl.PluralRules("ru").select(n);
  return rule === "one" ? one : rule === "few" ? few : many;
}

function tokens(n: number): string {
  return `${formatCount(n)} ${pluralRu(n, "токен", "токена", "токенов")}`;
}

/** Cost of one summary over `chars` characters, for `model`.
 *
 *  Returns null until the server answers, and null on failure -- a missing
 *  estimate must not block the button, it just means the price line stays
 *  empty rather than showing a wrong number. */
export function useEstimate(chars: number, model: string): EstimateResult | null {
  const [estimate, setEstimate] = useState<EstimateResult | null>(null);
  useEffect(() => {
    if (!chars || !model) {
      setEstimate(null);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      estimateCost(chars, model)
        .then((answer) => {
          if (live) setEstimate(answer);
        })
        .catch(() => {
          if (live) setEstimate(null);
        });
    }, 150);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [chars, model]);
  return estimate;
}

export type EstimateResultLike = EstimateResult | null;

export function PresetPicker({
  presets,
  value,
  onChange,
  disabled = false,
  name = "preset",
}: {
  presets: SettingsState["presets"];
  value: string;
  onChange: (preset: string) => void;
  disabled?: boolean;
  /** Shared `name` keeps the native radio group intact: arrow keys move within
   *  it, which a row of `role="radio"` buttons does not give you. */
  name?: string;
}) {
  return (
    <div role="radiogroup" aria-label="Что выбрать из разговора" className="grid gap-2">
      {presets.map((preset) => {
        const active = preset.key === value;
        return (
          <label
            key={preset.key}
            className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded border px-3 py-2 text-sm transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--ring)] ${
              active ? "border-accent-700 bg-accent-50 text-stone-900" : "border-stone-300 bg-sheet text-stone-700 hover:bg-stone-50"
            } ${disabled ? "pointer-events-none opacity-60" : ""}`}
          >
            <input
              type="radio"
              name={name}
              checked={active}
              disabled={disabled}
              onChange={() => onChange(preset.key)}
              className="h-4 w-4 shrink-0 accent-accent-700"
            />
            <span className="min-w-0">{preset.label}</span>
          </label>
        );
      })}
    </div>
  );
}

/** The pre-flight cost line. Says nothing it cannot support: with no price
 *  quoted for the model it shows the token count and stops there. */
export function EstimateLine({ estimate, waiting }: { estimate: EstimateResult | null; waiting: boolean }) {
  if (waiting && !estimate) {
    return <p className="text-xs text-stone-500">Считаем примерную стоимость…</p>;
  }
  if (!estimate) return null;
  const price = estimate.total === null ? null : formatMoney(estimate.total);
  return (
    <div className="space-y-1 text-xs text-stone-600">
      <p className="tabular-nums">
        {tokens(estimate.tokens_in)} текста уйдёт в модель
        {estimate.requests > 1 ? `, обращений к модели: ${estimate.requests}` : ""}
        {price ? <>, примерно {price}</> : null}
      </p>
      {estimate.requests > 1 ? (
        <p className="text-stone-500">
          Разговор длинный: текст сначала сжимается по частям, поэтому обращений к модели больше одного. После отправки
          покажем точную сумму.
        </p>
      ) : null}
      {price === null ? (
        <p className="text-stone-500">Стоимость зависит от провайдера и станет известна только после отправки.</p>
      ) : null}
    </div>
  );
}

/** The same figure as EstimateLine, cut to one phrase for the action bar. */
export function EstimateShort({ estimate, waiting }: { estimate: EstimateResult | null; waiting: boolean }) {
  if (!estimate) return <span>{waiting ? "Считаем стоимость…" : null}</span>;
  const price = estimate.total === null ? null : formatMoney(estimate.total);
  return (
    <span className="tabular-nums">
      {tokens(estimate.tokens_in)}
      {price ? `, примерно ${price}` : null}
    </span>
  );
}

/** The post-send figure, from the token counts the provider reported. */
export function ActualCostLine({
  cost,
  tokensIn,
  tokensOut,
}: {
  cost: { input: number | null; output: number | null; total: number | null };
  tokensIn: number | null;
  tokensOut: number | null;
}) {
  if (cost.total === null) {
    return tokensIn === null ? null : (
      <p className="tabular-nums text-xs text-stone-500">
        {tokens(tokensIn)} в модель, {tokens(tokensOut ?? 0)} обратно
      </p>
    );
  }
  return (
    <p className="tabular-nums text-xs text-stone-500">
      {formatMoney(cost.total)}, {tokens(tokensIn ?? 0)} в модель, {tokens(tokensOut ?? 0)} обратно
    </p>
  );
}