/** The one place a summary decision is made.
 *
 *  There used to be two: the pre-send review after a file loads, and a panel
 *  inside the finished document. They held the same controls but behaved
 *  differently -- one sent on click, the other asked first -- so the only way to
 *  learn which was safe was to try it. Same surface now, same words, same rule:
 *  the cost and the focus are shown before anything is sent, whatever brought
 *  you here.
 *
 *  It appears full-screen when there is no document yet, and in place inside the
 *  summary section when re-running one. Nothing is thrown away to get back here.
 */

import { EstimateLine, PresetPicker, type EstimateResultLike } from "./SummaryControls";
import { Button } from "./ui";
import type { SettingsState } from "./api";

export function ComposeGate({
  settings,
  preset,
  onPreset,
  estimate,
  busy,
  canRun,
  runLabel,
  onRun,
  onOpenSettings,
  /** Present when there is a document to return to. */
  onClose,
  closeLabel,
}: {
  settings: SettingsState;
  preset: string;
  onPreset: (preset: string) => void;
  estimate: EstimateResultLike;
  busy: boolean;
  canRun: boolean;
  runLabel: string;
  onRun: () => void;
  onOpenSettings: () => void;
  onClose?: () => void;
  closeLabel?: string;
}) {
  return (
    <div className="max-w-xl space-y-4">
      <PresetPicker presets={settings.presets} value={preset} onChange={onPreset} disabled={busy} />
      {settings.extra ? (
        <p className="border-l border-stone-300 pl-3 text-xs text-stone-600">
          Плюс ваше требование: «{settings.extra}»
        </p>
      ) : null}
      <EstimateLine estimate={estimate} waiting={busy} />

      <div className="flex flex-wrap items-center gap-4">
        {settings.has_key ? (
          <Button onClick={onRun} disabled={busy || !canRun} size="lg">
            {busy ? "Составляем…" : runLabel}
          </Button>
        ) : (
          <Button onClick={onOpenSettings} size="lg">
            Открыть настройки
          </Button>
        )}
        {onClose ? (
          <Button variant="text" onClick={onClose} disabled={busy}>
            {closeLabel}
          </Button>
        ) : null}
      </div>

      {!settings.has_key ? (
        <p className="text-xs text-stone-500">Без ключа модель не ответит. Расшифровка от этого не пострадает.</p>
      ) : !canRun ? (
        <p className="text-xs text-stone-500">
          Расшифровка этой записи больше не сохранена. Загрузите файл заново, это займёт столько же времени.
        </p>
      ) : null}
    </div>
  );
}