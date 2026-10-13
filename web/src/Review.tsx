/** The check that stands between the recording and the provider.
 *
 *  The app's whole promise is that personal data is stripped on this machine,
 *  and nothing else leaves. A promise nobody can inspect is a promise they have
 *  to take on faith -- so the masked text is shown in full here, before
 *  anything is sent, along with what the call will cost. Sending is a button
 *  press, not a side effect of dropping a file. */

import { useState } from "react";
import { MaskedView } from "./Highlight";
import { formatCount, humanDuration, pluralRu, useEstimate } from "./SummaryControls";
import { ComposeGate } from "./ComposeGate";
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
  const tokens = Object.keys(analysis.entity_map).length;
  const long = analysis.masked_text.length > PREVIEW_LIMIT;
  const speakers = new Set(analysis.segments.map((segment) => segment.speaker)).size;
  const canSend = !busy && settings.has_key;

  return (
    <article>
      <header>
        <h2 className="break-words text-2xl font-semibold tracking-tight text-slate-900">{name}</h2>
        <p className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[12px] tabular-nums text-slate-500">
          {humanDuration(analysis.duration_sec)}
          {speakers > 1 ? <span>{speakers} {pluralRu(speakers, "спикер", "спикера", "спикеров")}</span> : null}
        </p>
      </header>

      {/* The status of the privacy step, stated plainly: the work is done, and
          nothing has been sent yet. */}
      <div className="mt-6 flex items-start gap-3 border-l-2 border-emerald-400 bg-emerald-50 px-4 py-3">
        <ShieldCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
        <div className="text-sm">
          <p className="font-medium text-emerald-900">Расшифровка готова. Пока ничего не отправлено</p>
          {analysis.cached ? (
            <p className="mt-1 text-emerald-800">
              Эту запись мы уже разбирали раньше, поэтому показываем сохранённую расшифровку — заново не слушали.
            </p>
          ) : null}
          <p className="mt-1 text-emerald-800">
            {tokens > 0
              ? `Скрыто ${formatCount(tokens)} ${pluralRu(tokens, "значение", "значения", "значений")}: имена, телефоны, адреса, номера.`
              : "Личных данных не найдено."}{" "}
            Прочитайте текст ниже: это всё, что увидит модель.
          </p>
        </div>
      </div>

      <Section
        label="Что уйдёт в модель"
        meta={
          long && !full ? (
            <button onClick={() => setFull(true)} className="focus-ring rounded text-xs text-blue-700 underline">
              Показать целиком
            </button>
          ) : null
        }
      >
        <div className="max-h-[26rem] overflow-y-auto rounded border border-slate-200 bg-slate-50 p-3">
          {long && !full ? (
            <>
              <MaskedView text={analysis.masked_text.slice(0, PREVIEW_LIMIT)} entityMap={analysis.entity_map} />
              <p className="mt-2 text-xs text-slate-500">
                …и ещё {formatCount(analysis.masked_text.length - PREVIEW_LIMIT)} знаков
              </p>
            </>
          ) : (
            <MaskedView text={analysis.masked_text} entityMap={analysis.entity_map} />
          )}
        </div>
      </Section>

      <Section label="Какую выжимку составить">
        <ComposeGate
          settings={settings}
          preset={preset}
          onPreset={onPreset}
          estimate={estimate}
          busy={busy}
          canRun={canSend}
          runLabel="Составить выжимку"
          onRun={onSend}
          onOpenSettings={onOpenSettings}
        />
      </Section>

      {/* Leaving without a summary is a decision, not a dead end: the document
          below says so plainly and offers the same gate again. */}
      <div className="no-print mt-8 border-t border-slate-200 pt-6">
        <Button variant="text" onClick={onSkip} disabled={busy}>
          Оставить только расшифровку
        </Button>
      </div>
    </article>
  );
}
