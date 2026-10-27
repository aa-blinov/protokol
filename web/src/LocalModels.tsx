import { useCallback, useEffect, useState } from "react";
import {
  cancelLocalModels,
  deleteLocalModel,
  downloadLocalModels,
  getLocalModels,
  type LocalModel,
  type LocalModelsState,
  type ModelProgress,
} from "./api";
import { Button, ProgressBar, Section } from "./ui";

/** Decimal megabytes, the unit the download sizes are quoted in everywhere. */
function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_000_000)} МБ`;
}

/** What is left to transfer for a model, counting the bytes of an interrupted download. */
function remaining(model: LocalModel): number {
  return Math.max(0, model.missing - model.partial_bytes);
}

/** The models on this Mac: what is installed, what can still be fetched, and what can be
 *  removed to free the space. It sits outside the policy lock: the policy decides whether
 *  downloads are allowed at all, not how the models already on disk are managed. */
export function LocalModelsSection() {
  const [state, setState] = useState<LocalModelsState | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ModelProgress | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const refresh = useCallback(() => {
    getLocalModels()
      .then(setState)
      .catch((error: unknown) =>
        setMessage({ tone: "bad", text: error instanceof Error ? error.message : String(error) }),
      );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function fetchModels(ids: string[]) {
    setMessage(null);
    setBusy(true);
    setStartedAt(Date.now());
    const outcome: { stage: ModelProgress["stage"] | null; text: string } = { stage: null, text: "" };
    try {
      await downloadLocalModels(ids, (event) => {
        if (event.stage === "progress") setProgress(event);
        else {
          outcome.stage = event.stage;
          outcome.text = event.message ?? "";
        }
      });
      if (outcome.stage === "done") setMessage({ tone: "ok", text: "Модели скачаны." });
      else if (outcome.stage === "cancelled") {
        setMessage({ tone: "ok", text: "Загрузка остановлена. Скачанное сохранено." });
      }
    } catch (error) {
      setMessage({ tone: "bad", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
      setProgress(null);
      setStartedAt(null);
      refresh();
    }
  }

  async function remove(model: LocalModel) {
    if (!window.confirm(`Удалить «${model.title}» с этого Mac? Чтобы пользоваться им снова, его придётся скачать заново.`)) {
      return;
    }
    setMessage(null);
    try {
      const { freed } = await deleteLocalModel(model.id);
      setMessage({ tone: "ok", text: `Удалено, освобождено ${megabytes(freed)}.` });
    } catch (error) {
      setMessage({ tone: "bad", text: error instanceof Error ? error.message : String(error) });
    } finally {
      refresh();
    }
  }

  if (!state) return null;
  const missingAny = state.models.some((model) => !model.installed);
  const missingBytes = state.models.reduce((sum, model) => (model.installed ? sum : sum + remaining(model)), 0);
  const titleOf = (id?: string) => state.models.find((model) => model.id === id)?.title ?? "";

  return (
    <Section label="Модели на этом Mac">
      <ul className="divide-y divide-stone-200 rounded border border-stone-300">
        {state.models.map((model) => (
          <li key={model.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
            <div className="min-w-0">
              <p className="text-stone-800">
                {model.title}
                {model.required ? null : <span className="text-stone-500"> (необязательно)</span>}
              </p>
              <p className="text-xs text-stone-500">
                {model.installed
                  ? `установлено, ${megabytes(model.size)}`
                  : `осталось скачать ${megabytes(remaining(model))} из ${megabytes(model.size)}`}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              {model.installed ? (
                <Button variant="ghost" disabled={busy} onClick={() => void remove(model)}>
                  Удалить
                </Button>
              ) : (
                <Button variant="ghost" disabled={busy || !state.allowed} onClick={() => void fetchModels([model.id])}>
                  Скачать
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {!state.allowed ? (
        <p className="mt-2 text-xs text-amber-900">
          Загрузка моделей запрещена политикой организации. Файлы можно поместить в папку{" "}
          <span className="font-mono">{state.folder}</span> вручную.
        </p>
      ) : null}

      {busy && progress ? (
        <div className="mt-3 space-y-2">
          <ProgressBar
            pct={progress.total ? Math.round((100 * (progress.done ?? 0)) / progress.total) : 0}
            message={`${titleOf(progress.model)}: ${megabytes(progress.done ?? 0)} из ${megabytes(progress.total ?? 0)}`}
            startedAt={startedAt}
          />
          <Button variant="ghost" onClick={() => void cancelLocalModels()}>
            Остановить
          </Button>
        </div>
      ) : null}

      {!busy && missingAny && state.allowed ? (
        <Button
          className="mt-3"
          onClick={() => void fetchModels(state.models.filter((model) => !model.installed).map((model) => model.id))}
        >
          Скачать недостающее ({megabytes(missingBytes)})
        </Button>
      ) : null}

      {message ? (
        <p role="status" className={`mt-2 text-sm ${message.tone === "bad" ? "text-red-700" : "text-stone-700"}`}>
          {message.text}
        </p>
      ) : null}
    </Section>
  );
}
