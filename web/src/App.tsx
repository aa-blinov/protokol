import { useCallback, useEffect, useRef, useState } from "react";
import {
  getHealth,
  processAudio,
  type Entity,
  type ProcessResult,
  type ProgressEvent,
  type Session,
} from "./api";
import { chipClass, Highlighted, MaskedView } from "./Highlight";
import { Badge, Button, Card, EmptyState, ProgressBar } from "./ui";

const PRODUCT_NAME = "Стенограф";

// Русские числительные требуют трёх форм; Intl.PluralRules закрывает краевые
// случаи (11–14), которые ломают ручные формулы.
function pluralRu(n: number, one: string, few: string, many: string): string {
  const rule = new Intl.PluralRules("ru").select(n);
  return rule === "one" ? one : rule === "few" ? few : many;
}

// Entities carry offsets into the whole transcript; a speaker turn shows only
// the spans inside its own slice, shifted to the slice's start.
function entitiesWithin(entities: Entity[], offset: number, length: number): Entity[] {
  const end = offset + length;
  return entities
    .filter((entity) => entity.start >= offset && entity.end <= end)
    .map((entity) => ({ ...entity, start: entity.start - offset, end: entity.end - offset }));
}

// Speaker labels stay monochrome: colour is reserved for masked entities
// (DESIGN.md, "The Colour-Means-PII Rule"), so identity is carried by the
// number and a subtle neutral shade, never a hue.
const SPEAKER_STYLES = ["border-slate-300 bg-slate-100 text-slate-700", "border-slate-300 bg-white text-slate-700"];

function speakerLabel(speaker: number): string {
  return `Спикер ${speaker + 1}`;
}

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** The transcript as copyable text: speaker turns when diarized, else plain. */
function transcriptText(result: ProcessResult): string {
  if (result.segments.length === 0) return result.transcript;
  return result.segments.map((segment) => `${speakerLabel(segment.speaker)}: ${segment.text}`).join("\n");
}

function buildReport(session: Session): string {
  const result = session.result;
  return [
    `${PRODUCT_NAME} — расшифровка встречи`,
    `Файл: ${session.name}`,
    `Дата: ${new Date(session.createdAt).toLocaleString("ru-RU")}`,
    `Длительность: ${result.duration_sec.toFixed(1)} с`,
    `Модель: ${result.llm_model}`,
    "",
    "ТРАНСКРИПЦИЯ",
    transcriptText(result),
    "",
    "МАСКИРОВАННЫЙ ТЕКСТ (ушёл в LLM)",
    result.masked_text,
    "",
    "ОТВЕТ МОДЕЛИ",
    result.reply_unmasked,
    "",
  ].join("\n");
}

function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function CopyButton({ text, label = "Скопировать" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — the download button still works */
    }
  };
  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="focus-ring rounded-md border border-slate-200 px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-700"
    >
      {copied ? "Скопировано" : label}
    </button>
  );
}

const STORAGE_KEY = "sttshka.sessions";
const DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash";

function loadSessions(): Session[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as Session[];
  } catch {
    return [];
  }
}

export default function App() {
  const [sessions, setSessions] = useState<Session[]>(loadSessions);
  const [current, setCurrent] = useState<Session | null>(null);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 50)));
  }, [sessions]);

  useEffect(() => {
    getHealth()
      .then((health) => setLlmConfigured(health.llm_configured))
      .catch(() => setLlmConfigured(null));
  }, []);

  const run = useCallback(
    async (file: File) => {
      setError(null);
      setProgress({ stage: "transcribe", pct: 0, message: "Загрузка файла" });
      try {
        const result: ProcessResult = await processAudio(file, model, setProgress);
        const session: Session = {
          id: crypto.randomUUID(),
          name: file.name,
          createdAt: new Date().toISOString(),
          result,
        };
        setSessions((previous) => [session, ...previous].slice(0, 50));
        setCurrent(session);
      } catch (caught) {
        // The failed file is not the session on screen — drop that stale result,
        // otherwise the error reads as belonging to the panels below it.
        setCurrent(null);
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setProgress(null);
      }
    },
    [model],
  );

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void run(file);
  };

  const dropHandlers = {
    onDragOver: (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(true);
    },
    onDragLeave: () => setDragging(false),
    onDrop,
  };

  const removeSession = (id: string) => {
    setSessions((previous) => previous.filter((session) => session.id !== id));
    setCurrent((active) => (active?.id === id ? null : active));
  };

  const result = current?.result;
  const busy = progress !== null;
  const showDropTarget = !result && !busy;

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold tracking-tight text-slate-900">{PRODUCT_NAME}</h1>
            <p className="truncate text-xs text-slate-500">Приватная расшифровка встреч</p>
          </div>
          <div className="ml-auto">
            <Button
              variant="ghost"
              onClick={() => setSettingsOpen((open) => !open)}
              ariaLabel="Настройки"
              ariaExpanded={settingsOpen}
            >
              Настройки
            </Button>
          </div>
        </div>

        {settingsOpen ? (
          <div className="border-t border-slate-100 bg-slate-50">
            <div className="mx-auto flex max-w-7xl flex-wrap items-end gap-x-8 gap-y-3 px-5 py-3">
              <label className="flex flex-col gap-1 text-xs text-slate-600">
                Модель LLM
                <input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  className="focus-ring w-64 rounded-md border border-slate-300 bg-white px-2 py-1.5 font-mono text-xs"
                  aria-label="Модель LLM"
                />
              </label>
              <div className="flex flex-col gap-1 text-xs text-slate-600">
                Ключ OpenRouter
                <span className={llmConfigured ? "text-emerald-700" : "text-amber-700"}>
                  {llmConfigured === null ? "проверяем…" : llmConfigured ? "настроен" : "не задан"}
                </span>
              </div>
              <p className="max-w-md text-xs text-slate-500">
                Ключ хранится в <span className="font-mono">.env</span> рядом с приложением и не попадает в сборку.
                Смена модели действует на новые записи.
              </p>
            </div>
          </div>
        ) : null}
      </header>

      <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-5 py-6 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">История сессий</h2>
          {sessions.length === 0 ? (
            <p className="text-sm text-slate-500">Пока пусто.</p>
          ) : (
            <ul className="space-y-1.5">
              {sessions.map((session) => (
                <li key={session.id} className="relative">
                  <button
                    onClick={() => setCurrent(session)}
                    className={`focus-ring w-full rounded-md border py-2 pl-3 pr-9 text-left transition-colors ${
                      current?.id === session.id
                        ? "border-blue-300 bg-blue-50"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                  >
                    <div className="truncate text-sm font-medium text-slate-800">{session.name}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                      <span>{new Date(session.createdAt).toLocaleString("ru-RU")}</span>
                      <span>· {session.result.entities.length} PII</span>
                    </div>
                  </button>
                  <button
                    onClick={() => removeSession(session.id)}
                    aria-label={`Удалить сессию ${session.name}`}
                    title="Удалить"
                    className="focus-ring absolute right-1.5 top-1.5 rounded-md px-1.5 py-0.5 text-base leading-none text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <main className="space-y-5">
          <input
            ref={inputRef}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.mp4"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void run(file);
              event.target.value = "";
            }}
          />

          {showDropTarget ? (
            <div
              {...dropHandlers}
              className={`rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
                dragging ? "border-blue-500 bg-blue-50" : "border-slate-300 bg-white"
              }`}
            >
              <p className="text-sm font-medium text-slate-800">Перетащите запись встречи сюда</p>
              <p className="mt-1 text-sm text-slate-500">
                WAV, MP3, M4A, OGG. Запись до часа, аудио обрабатывается локально.
              </p>
              <div className="mt-4">
                <Button onClick={() => inputRef.current?.click()} disabled={busy}>
                  Выбрать аудиофайл
                </Button>
              </div>
            </div>
          ) : (
            <div
              {...dropHandlers}
              className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-2.5 transition-colors ${
                dragging ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white"
              }`}
            >
              <span className="text-sm text-slate-600">Перетащите сюда следующую запись или</span>
              <Button variant="ghost" onClick={() => inputRef.current?.click()} disabled={busy}>
                Обработать ещё
              </Button>
            </div>
          )}

          {llmConfigured === false ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
              <p className="text-sm font-medium text-amber-900">Ключ OpenRouter не задан</p>
              <p className="mt-1 text-sm text-amber-800">
                Запись расшифруется и обезличится, но ответа модели не будет. Добавьте{" "}
                <span className="font-mono">OPENROUTER_API_KEY</span> в файл <span className="font-mono">.env</span>{" "}
                рядом с приложением и перезапустите его.
              </p>
            </div>
          ) : null}

          {busy && progress ? (
            <Card title="Обработка" accent="#1d4ed8">
              <ProgressBar pct={progress.pct} message={progress.message} />
            </Card>
          ) : null}

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
              <p className="text-sm font-medium text-red-900">Не удалось обработать запись</p>
              <p className="mt-1 text-sm text-red-800">{error}</p>
            </div>
          ) : null}

          {!result && !busy && !error ? (
            <EmptyState
              title="Здесь появится расшифровка"
              hint="После обработки будут три панели: что сказано, что именно уходит в модель и её ответ."
            />
          ) : null}

          {result && current ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="blue">Длительность {result.duration_sec.toFixed(1)} сек</Badge>
                <Badge tone={result.entities.length ? "amber" : "green"}>ПДн: {result.entities.length}</Badge>
                <Badge tone="slate">Модель: {result.llm_model}</Badge>
                <button
                  type="button"
                  onClick={() =>
                    downloadText(`${current.name.replace(/\.[^.]+$/, "")} — расшифровка.txt`, buildReport(current))
                  }
                  className="focus-ring ml-auto rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50"
                >
                  Скачать отчёт
                </button>
              </div>

              <Card
                title="1 · Что сказано"
                accent="#64748b"
                meta={
                  <span className="flex items-center gap-2">
                    {result.segments.length > 0 ? (
                      <span>
                        {new Set(result.segments.map((segment) => segment.speaker)).size}{" "}
                        {pluralRu(
                          new Set(result.segments.map((segment) => segment.speaker)).size,
                          "спикер",
                          "спикера",
                          "спикеров",
                        )}
                      </span>
                    ) : null}
                    <CopyButton text={transcriptText(result)} />
                  </span>
                }
              >
                {result.segments.length > 0 ? (
                  <ul className="space-y-3">
                    {result.segments.map((segment, index) => (
                      <li key={index} className="flex gap-3">
                        <div className="flex w-24 shrink-0 flex-col items-start gap-1">
                          <span
                            className={`rounded-md border px-1.5 py-0.5 text-xs font-medium ${
                              SPEAKER_STYLES[segment.speaker % SPEAKER_STYLES.length]
                            }`}
                          >
                            {speakerLabel(segment.speaker)}
                          </span>
                          <span className="font-mono text-[11px] text-slate-400">{formatTime(segment.start)}</span>
                        </div>
                        <div className="min-w-0 flex-1">
                          <Highlighted
                            text={segment.text}
                            entities={entitiesWithin(result.entities, segment.offset, segment.text.length)}
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Highlighted text={result.transcript} entities={result.entities} />
                )}
              </Card>

              <Card
                title="2 · Что уходит в модель"
                accent="#1d4ed8"
                meta={
                  <span className="font-mono">
                    {Object.keys(result.entity_map).length}{" "}
                    {pluralRu(Object.keys(result.entity_map).length, "токен", "токена", "токенов")}
                  </span>
                }
              >
                <MaskedView text={result.masked_text} entityMap={result.entity_map} />
                {Object.keys(result.entity_map).length > 0 ? (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                      Таблица подстановок
                    </summary>
                    <ul className="mt-2 space-y-1">
                      {Object.entries(result.entity_map).map(([token, value]) => (
                        <li key={token} className="flex items-baseline gap-2 text-xs">
                          <span className={chipClass(token.replace(/_\d+$/, ""))}>{token}</span>
                          <span className="font-mono text-slate-600">{value}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </Card>

              <Card
                title="3 · Ответ модели"
                accent="#0f766e"
                meta={<CopyButton text={result.reply_unmasked} />}
              >
                <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{result.reply_unmasked}</p>
                <details className="mt-3">
                  <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                    Ответ до обратной подстановки
                  </summary>
                  <div className="mt-2 rounded-md bg-slate-50 p-3">
                    <MaskedView text={result.reply} entityMap={result.entity_map} />
                  </div>
                </details>
              </Card>
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}
