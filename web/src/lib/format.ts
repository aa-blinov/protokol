import { readable, writable, type Readable } from "svelte/store";
import { estimateCost } from "../api";
import type { EstimateResult } from "../api";

/** A duration as a person says it: 1 ч 05 мин, 12 мин 30 с, 44 с. */
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
 *  a row of zeroes. The sum is shown as a decimal when it is worth a decimal
 *  and as a count of cents when it is not. */
export function formatMoney(value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0,00";
  if (value < 0.01) return `${(value * 100).toFixed(2)} ¢`;
  return `$${value.toFixed(2)}`;
}

/** A count with the separators this language writes them with. */
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

export function tokens(n: number): string {
  return `${formatCount(n)} ${pluralRu(n, "токен", "токена", "токенов")}`;
}

/** What one summary will roughly cost, before it is sent.
 *
 *  Null until the server answers and null on failure: a missing estimate must
 *  not block the button, it only means the price line stays empty. */
export function useEstimate(chars: number, model: string): Readable<EstimateResult | null> {
  const estimate = writable<EstimateResult | null>(null);
  let request = 0;

  const refresh = async (nextChars: number, nextModel: string) => {
    if (!nextModel || nextChars <= 0) {
      estimate.set(null);
      return;
    }
    const mine = (request += 1);
    try {
      const answer = await estimateCost(nextChars, nextModel);
      if (mine === request) estimate.set(answer);
    } catch (error) {
      if (mine === request) estimate.set(null);
    }
  };

  void refresh(chars, model);
  return { subscribe: estimate.subscribe };
}

/** The same estimate, as a plain promise, for the places that want it once. */
export function estimateOnce(chars: number, model: string): Promise<EstimateResult | null> {
  return estimateCost(chars, model).catch(() => null);
}

export { readable };
