import { useState } from "react";
import {
  cancelLocalModels,
  downloadLocalModels,
  type LocalModelsState,
  type ModelProgress,
} from "./api";
import { Button, ProgressBar } from "./ui";

/** Decimal megabytes, the unit the download sizes are quoted in everywhere. */
function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_000_000)} МБ`;
}

/** Shown in place of the app until the models it needs are on disk. The models are
 *  public files from Hugging Face, fetched once; nothing about the person is sent. */
export function FirstRun({ state, onRefresh }: { state: LocalModelsState; onRefresh: () => void }) {
  const required = state.models.filter((model) => model.required);
  const optional = state.models.find((model) => !model.required);
  const [withSpeakers, setWithSpeakers] = useState(true);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<ModelProgress | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const wanted = [
    ...required.filter((model) => !model.installed),
    ...(withSpeakers && optional && !optional.installed ? [optional] : []),
  ];
  // What is left to transfer: bytes of an interrupted download are already on disk.
  const toFetch = wanted.reduce((sum, model) => sum + Math.max(0, model.missing - model.partial_bytes), 0);
  const titleOf = (id?: string) => state.models.find((model) => model.id === id)?.title ?? "";
  const pct = progress?.total ? Math.round((100 * (progress.done ?? 0)) / progress.total) : 0;

  async function start() {
    setFailure(null);
    setNotice(null);
    setRunning(true);
    setStartedAt(Date.now());
    // An object, not a plain variable: TypeScript cannot see the callback write to it.
    const outcome: { stage: ModelProgress["stage"] | null } = { stage: null };
    try {
      await downloadLocalModels(
        wanted.map((model) => model.id),
        (event) => {
          if (event.stage === "progress") setProgress(event);
          else outcome.stage = event.stage;
        },
      );
      if (outcome.stage === "cancelled") {
        setNotice("Загрузка остановлена. Скачанное сохранено, продолжим с этого места.");
      }
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setRunning(false);
      setProgress(null);
      setStartedAt(null);
      // Re-read the state after every attempt: a finished download opens the app, and
      // a stopped or failed one shows what is left, counting the bytes already on disk.
      onRefresh();
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-6 py-10">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold text-stone-900">Нужно скачать модели</h1>
        <p className="text-sm leading-6 text-stone-600">
          Распознавание речи и поиск персональных данных работают на этом Mac, без облака.
          Модели скачиваются один раз с Hugging Face. После этого сеть нужна только для
          выжимки, и то лишь к адресу провайдера.
        </p>
      </header>

      {!state.allowed ? (
        <p className="rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Загрузка моделей запрещена политикой организации. Поместите файлы моделей в папку{" "}
          <span className="font-mono text-xs">{state.folder}</span> или обратитесь к администратору.
        </p>
      ) : null}

      <ul className="divide-y divide-stone-200 rounded border border-stone-300">
        {state.models.map((model) => (
          <li key={model.id} className="flex items-baseline justify-between gap-3 px-4 py-3 text-sm">
            <span className="text-stone-800">
              {model.title}
              {model.required ? null : <span className="text-stone-500"> (необязательно)</span>}
            </span>
            <span className="shrink-0 text-stone-500">
              {model.installed ? "установлено" : megabytes(model.size)}
            </span>
          </li>
        ))}
      </ul>

      {optional && !optional.installed ? (
        <label className="flex items-center gap-2 text-sm text-stone-700">
          <input
            type="checkbox"
            checked={withSpeakers}
            disabled={running}
            onChange={(event) => setWithSpeakers(event.target.checked)}
          />
          Разделять говорящих: без этого метки «Спикер» не появятся
        </label>
      ) : null}

      {running && progress ? (
        <ProgressBar
          pct={pct}
          message={`${titleOf(progress.model)}: ${megabytes(progress.done ?? 0)} из ${megabytes(progress.total ?? 0)}`}
          startedAt={startedAt}
        />
      ) : null}

      {failure ? (
        <p role="alert" className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
          {failure} Уже скачанное не пропадёт: повторите, и загрузка продолжится.
        </p>
      ) : null}
      {notice ? <p className="text-sm text-stone-600">{notice}</p> : null}

      {state.allowed ? (
        <div className="flex flex-wrap items-center gap-3">
          {running ? (
            <Button variant="ghost" onClick={() => void cancelLocalModels()}>
              Остановить
            </Button>
          ) : (
            <Button
              size="lg"
              onClick={() => void start()}
              disabled={toFetch === 0}
            >
              {toFetch === 0 ? "Всё скачано" : `Скачать модели (${megabytes(toFetch)})`}
            </Button>
          )}
        </div>
      ) : null}

      <p className="font-mono text-xs text-stone-500">Папка моделей: {state.folder}</p>
    </main>
  );
}
