import { useCallback, useEffect, useRef, useState } from "react";
import { processAudio, type ProcessResult, type ProgressEvent, type Session } from "./api";
import { chipClass, Highlighted, MaskedView } from "./Highlight";
import { Badge, Button, Card, EmptyState, ProgressBar } from "./ui";

const STORAGE_KEY = "sttshka.sessions";
const DEFAULT_MODEL = "openai/gpt-4o-mini";

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
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 50)));
  }, [sessions]);

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

  const result = current?.result;
  const busy = progress !== null;

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
          <h1 className="text-base font-semibold tracking-tight text-slate-900">STT → PII → OpenRouter</h1>
          <Badge tone="green">Личный инструмент</Badge>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-600">
              Модель LLM
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                className="focus-ring w-56 rounded-md border border-slate-300 bg-white px-2 py-1.5 font-mono text-xs"
                aria-label="Модель LLM"
              />
            </label>
            <Button variant="ghost" onClick={() => inputRef.current?.click()} disabled={busy}>
              Выбрать файл
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 px-5 py-6 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">История сессий</h2>
          {sessions.length === 0 ? (
            <p className="text-sm text-slate-500">Пока пусто.</p>
          ) : (
            <ul className="space-y-1.5">
              {sessions.map((session) => (
                <li key={session.id}>
                  <button
                    onClick={() => setCurrent(session)}
                    className={`focus-ring w-full rounded-md border px-3 py-2 text-left transition-colors ${
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
                </li>
              ))}
            </ul>
          )}
        </aside>

        <main className="space-y-5">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${
              dragging ? "border-blue-500 bg-blue-50" : "border-slate-300 bg-white"
            }`}
          >
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
            <p className="text-sm font-medium text-slate-800">Перетащите запись звонка сюда</p>
            <p className="mt-1 text-sm text-slate-500">
              WAV, MP3, M4A, OGG — до часа. Аудио обрабатывается локально.
            </p>
            <div className="mt-4">
              <Button onClick={() => inputRef.current?.click()} disabled={busy}>
                Выбрать аудиофайл
              </Button>
            </div>
          </div>

          {busy && progress ? (
            <Card title="Обработка">
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
              title="Результаты появятся здесь"
              hint="Транскрипция, маскированный текст и ответ модели — три панели, чтобы было видно, что именно уходит в LLM."
            />
          ) : null}

          {result ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="blue">Длительность {result.duration_sec.toFixed(1)} сек</Badge>
                <Badge tone={result.entities.length ? "amber" : "green"}>
                  PII: {result.entities.length}
                </Badge>
                <Badge tone="slate">Модель: {result.llm_model}</Badge>
                {Object.entries(result.timings).map(([stage, seconds]) => (
                  <Badge key={stage} tone="slate">
                    {stage}: {seconds.toFixed(1)}с
                  </Badge>
                ))}
              </div>

              <Card title="1 · Транскрипция" accent="#64748b">
                <Highlighted text={result.transcript} entities={result.entities} />
              </Card>

              <Card
                title="2 · Маскированный текст — именно он уходит в LLM"
                accent="#1d4ed8"
                meta={<span className="font-mono">{Object.keys(result.entity_map).length} токенов</span>}
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

              <Card title="3 · Ответ модели" accent="#0f766e">
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
