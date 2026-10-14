/** The check that stands between the recording and the provider.
 *
 *  The app's whole promise is that personal data is stripped on this machine,
 *  and nothing else leaves. A promise nobody can inspect is a promise they have
 *  to take on faith -- so the masked text is shown in full here, before
 *  anything is sent, along with what the call will cost. Sending is a button
 *  press, not a side effect of dropping a file.
 *
 *  The decision sits in a bar that stays on screen. The text is long, and a
 *  send button that waits at the bottom of it is one people never reach. */

import { useState } from "react";
import { MaskedView } from "./Highlight";
import { EstimateShort, PresetPicker, formatCount, humanDuration, pluralRu, useEstimate } from "./SummaryControls";
import { Button, Section } from "./ui";
import { ShieldCheck } from "lucide-react";
import type { AnalysisResult, SettingsState } from "./api";

/** Above this the preview is cut and the rest is one click away. An hour of
 *  conversation is a lot of text to put in front of someone before they have
 *  agreed to spend anything. */
const PREVIEW_LIMIT = 3000;

export function Review({
  name,
  analysis,
  settings,
  preset,
  onPreset,
  onSend,
  onSkip,
  onOpenSettings,
  busy,
}: {
  name: string;
  analysis: AnalysisResult;
  settings: SettingsState;
  preset: string;
  onPreset: (preset: string) => void;
  onSend: () => void;
  /** Keep the transcript and stop there -- no provider call, no cost. */
  onSkip: () => void;
  onOpenSettings: () => void;
  busy: boolean;
}) {
  const [full, setFull] = useState(false);
  const estimate = useEstimate(analysis.masked_text.length, settings.model);
  const hidden = Object.keys(analysis.entity_map).length;
  const long = analysis.masked_text.length > PREVIEW_LIMIT;
  const speakers = new Set(analysis.segments.map((segment) => segment.speaker)).size;
  const canSend = !busy && settings.has_key;
  // The bar sends whatever focus is picked above it, so the bar names it too.
  const focusLabel = settings.presets.find((item) => item.key === preset)?.label ?? "";

  return (
    <article>
      <header>
        <h2 className="break-words text-2xl font-semibold tracking-tight text-stone-900">{name}</h2>
        <p className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[12px] tabular-nums text-stone-500">
          {humanDuration(analysis.duration_sec)}
          {speakers > 1 ? <span>{speakers} {pluralRu(speakers, "спикер", "спикера", "спикеров")}</span> : null}
        </p>
      </header>

      {/* The privacy step, stated once: the work is done and nothing has left yet. */}
      <div className="mt-6 flex items-start gap-3 border border-accent-300 bg-accent-50 px-4 py-3">
        <ShieldCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-accent-700" />
        <div className="text-sm">
          <p className="font-medium text-accent-900">Ничего не отправлено</p>
          <p className="mt-1 text-accent-800">
            {hidden > 0
              ? `Скрыто ${formatCount(hidden)} ${pluralRu(hidden, "значение", "значения", "значений")}. Это весь текст, который увидит модель.`
              : "Личных данных не найдено. Это весь текст, который увидит модель."}
          </p>
        </div>
      </div>

      <Section
        label="Что уйдёт в модель"
        meta={
          long && !full ? (
            <button onClick={() => setFull(true)} className="focus-ring rounded text-xs text-accent-700 underline">
              Показать целиком
            </button>
          ) : null
        }
      >
        <div className="max-h-[26rem] overflow-y-auto rounded border border-stone-200 bg-stone-50 p-3">
          {long && !full ? (
            <>
              <MaskedView text={analysis.masked_text.slice(0, PREVIEW_LIMIT)} entityMap={analysis.entity_map} />
              <p className="mt-2 text-xs text-stone-500">
                …и ещё {formatCount(analysis.masked_text.length - PREVIEW_LIMIT)} знаков
              </p>
            </>
          ) : (
            <MaskedView text={analysis.masked_text} entityMap={analysis.entity_map} />
          )}
        </div>
      </Section>

      <Section label="Что выделить в выжимке">
        <div className="max-w-xl">
          <PresetPicker presets={settings.presets} value={preset} onChange={onPreset} disabled={busy} />
          {settings.extra ? (
            <p className="mt-3 border-l border-stone-300 pl-3 text-xs text-stone-600">
              Плюс ваше требование: «{settings.extra}»
            </p>
          ) : null}
        </div>
      </Section>

      <div className="no-print sticky bottom-0 -mx-6 mt-10 border-t border-stone-200 bg-sheet px-6 py-3">
        <div className="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:gap-x-4">
          <p className="min-w-0 flex-1 basis-full text-xs text-stone-600 md:basis-auto">
            {settings.has_key ? (
              <>
                <span className="text-stone-900">{focusLabel}</span>
                {" · "}
                <EstimateShort estimate={estimate} waiting={busy} />
              </>
            ) : (
              "Без ключа модель не ответит. Расшифровка от этого не пострадает."
            )}
          </p>
          <div className="flex w-full flex-col-reverse gap-2 md:w-auto md:shrink-0 md:flex-row md:items-center md:gap-3">
            <Button variant="text" onClick={onSkip} disabled={busy} className="whitespace-nowrap">
              Только расшифровка
            </Button>
            {settings.has_key ? (
              <Button size="lg" onClick={onSend} disabled={!canSend} className="w-full whitespace-nowrap md:w-auto">
                {busy ? "Составляем…" : "Составить выжимку"}
              </Button>
            ) : (
              <Button size="lg" onClick={onOpenSettings} className="w-full whitespace-nowrap md:w-auto">
                Открыть настройки
              </Button>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
