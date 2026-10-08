import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getHealth,
  processAudio,
  type Entity,
  type ProcessResult,
  type ProgressEvent,
  type Session,
} from "./api";
import { chipClass, Highlighted, MaskedView } from "./Highlight";
import { Button, CopyButton, Markdown, ProgressBar, Section } from "./ui";

const PRODUCT_NAME = "Протокол";
const STORAGE_KEY = "sttshka.sessions";
const THEME_KEY = "sttshka.theme";
const DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash";

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

function loadSessions(): Session[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as Session[];
  } catch {
    return [];
  }
}

/** The product mark — same shape as the app icon and favicon. */
function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label={PRODUCT_NAME}>
      <rect width="32" height="32" rx="7" fill="#1d4ed8" />
      <rect x="7" y="11" width="18" height="3.5" rx="1.75" fill="#ffffff" />
      <rect x="7" y="17.5" width="11" height="3.5" rx="1.75" fill="#ffffff" opacity="0.72" />
    </svg>
  );
}

/** The raised document: file header, then the pipeline sections. */
function Document({
  session,
  onAnother,
}: {
  session: Session;
  onAnother: () => void;
}) {
  const result = session.result;
  const speakers = useMemo(() => new Set(result.segments.map((segment) => segment.speaker)).size, [result]);
  const tokens = Object.keys(result.entity_map).length;

  return (
    <article>
      <header>
        <h2 className="break-words text-2xl font-semibold tracking-tight text-slate-900">{session.name}</h2>
        <p className="mt-2 font-mono text-xs tabular-nums text-slate-500">
          {new Date(session.createdAt).toLocaleString("ru-RU")} · {result.duration_sec.toFixed(1)} с ·{" "}
          {result.entities.length} {pluralRu(result.entities.length, "ПДн", "ПДн", "ПДн")}
          {speakers > 1 ? ` · ${speakers} ${pluralRu(speakers, "спикер", "спикера", "спикеров")}` : ""} ·{" "}
          {result.llm_model}
        </p>
        <div className="no-print mt-4 flex flex-wrap items-center gap-4">
          <Button
            variant="ghost"
            onClick={() => downloadText(`${session.name.replace(/\.[^.]+$/, "")} — расшифровка.txt`, buildReport(session))}
          >
            Скачать .txt
          </Button>
          <Button variant="ghost" onClick={() => window.print()}>
            Печать / PDF
          </Button>
          <Button variant="text" onClick={onAnother}>
            Обработать ещё
          </Button>
        </div>
      </header>

      <Section label="Транскрипт" meta={<CopyButton text={transcriptText(result)} />}>
        {result.segments.length > 0 ? (
          <ul className="space-y-5">
            {result.segments.map((segment, index) => (
              <li key={index} className="grid grid-cols-[92px_1fr] gap-4">
                <div className="pt-1 leading-tight">
                  <div className="font-mono text-[11px] text-slate-500">{speakerLabel(segment.speaker)}</div>
                  <div className="mt-0.5 font-mono text-[11px] tabular-nums text-slate-400">
                    {formatTime(segment.start)}
                  </div>
                </div>
                <div className="max-w-[68ch] text-[15px] leading-7 text-slate-800">
                  <Highlighted
                    text={segment.text}
                    entities={entitiesWithin(result.entities, segment.offset, segment.text.length)}
                  />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="max-w-[68ch] text-[15px] leading-7 text-slate-800">
            <Highlighted text={result.transcript} entities={result.entities} />
          </div>
        )}
      </Section>

      <Section
        label="Что уходит в модель"
        meta={
          <span className="font-mono tabular-nums">
            {tokens} {pluralRu(tokens, "токен", "токена", "токенов")}
          </span>
        }
      >
        <div className="max-w-[68ch] text-[15px] leading-7 text-slate-800">
          <MaskedView text={result.masked_text} entityMap={result.entity_map} />
        </div>
        {tokens > 0 ? (
          <details className="no-print mt-4">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
              Таблица подстановок
            </summary>
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {Object.entries(result.entity_map).map(([token, value]) => (
                <li key={token} className="flex items-baseline gap-2 text-xs">
                  <span className={chipClass(token.replace(/_\d+$/, ""))}>{token}</span>
                  <span className="font-mono text-slate-600">{value}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </Section>

      <Section label="Ответ модели" meta={<CopyButton text={result.reply_unmasked} />}>
        <Markdown text={result.reply_unmasked} />
        <details className="no-print mt-4">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
            Ответ до обратной подстановки
          </summary>
          <div className="mt-3 max-w-[68ch] rounded border border-slate-200 bg-slate-50 p-3 text-[13px] leading-6 text-slate-600">
            <MaskedView text={result.reply} entityMap={result.entity_map} />
          </div>
        </details>
      </Section>
    </article>
  );
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
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light",
  );
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

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
        // otherwise the error reads as belonging to the document below it.
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

  const renameSession = (id: string, name: string) => {
    const trimmed = name.trim();
    setSessions((previous) => previous.map((session) => (session.id === id ? { ...session, name: trimmed || session.name } : session)));
    setEditingId(null);
  };

  const visibleSessions = query
    ? sessions.filter((session) => session.name.toLowerCase().includes(query.trim().toLowerCase()))
    : sessions;

  const result = current?.result;
  const busy = progress !== null;

  return (
    <div className="min-h-full">
      <header className="no-print sticky top-0 z-10 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <Mark className="h-7 w-7 shrink-0" />
          <div className="min-w-0">
            <h1 className="text-lg font-semibold tracking-tight text-slate-900">{PRODUCT_NAME}</h1>
            <p className="text-xs text-slate-500">Приватная расшифровка встреч</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              onClick={() => setTheme((value) => (value === "dark" ? "light" : "dark"))}
              ariaLabel={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            >
              {theme === "dark" ? "Светлая" : "Тёмная"}
            </Button>
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
            <div className="mx-auto flex max-w-5xl flex-wrap items-end gap-x-8 gap-y-3 px-6 py-4">
              <label className="flex flex-col gap-1 text-xs text-slate-600">
                Модель LLM
                <input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  className="focus-ring w-64 rounded border border-slate-300 bg-white px-2 py-1.5 font-mono text-xs"
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
              </p>
            </div>
          </div>
        ) : null}
      </header>

      <div className="mx-auto grid max-w-5xl grid-cols-1 gap-x-10 gap-y-8 px-6 py-8 lg:grid-cols-[200px_1fr] print:grid-cols-1">
        <aside className="no-print">
          <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">История</h2>
          {sessions.length > 0 ? (
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Поиск"
              aria-label="Поиск по истории"
              className="focus-ring mt-3 w-full rounded border border-slate-200 bg-white px-2 py-1 text-sm placeholder:text-slate-400"
            />
          ) : null}
          {sessions.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">Пока пусто</p>
          ) : visibleSessions.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">Ничего не найдено</p>
          ) : (
            <ul className="mt-2 space-y-0.5">
              {visibleSessions.map((session) => (
                <li key={session.id} className="group flex items-start">
                  {editingId === session.id ? (
                    <input
                      autoFocus
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      onBlur={() => renameSession(session.id, draft)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") event.currentTarget.blur();
                        if (event.key === "Escape") setEditingId(null);
                      }}
                      aria-label="Новое имя сессии"
                      className="focus-ring min-w-0 flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                    />
                  ) : (
                    <>
                      <button
                        onClick={() => setCurrent(session)}
                        className={`focus-ring min-w-0 flex-1 rounded px-2 py-1 text-left transition-colors ${
                          current?.id === session.id ? "bg-slate-100 text-blue-700" : "text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        <span className="block truncate text-sm">{session.name}</span>
                        <span className="font-mono text-[11px] tabular-nums text-slate-400">
                          {new Date(session.createdAt).toLocaleDateString("ru-RU")} · {session.result.entities.length} ПДн
                        </span>
                      </button>
                      <button
                        onClick={() => {
                          setEditingId(session.id);
                          setDraft(session.name);
                        }}
                        aria-label={`Переименовать сессию ${session.name}`}
                        title="Переименовать"
                        className="focus-ring mt-1 rounded px-1 text-xs leading-none text-slate-300 opacity-0 transition-opacity hover:text-slate-600 group-hover:opacity-100"
                      >
                        ✎
                      </button>
                      <button
                        onClick={() => removeSession(session.id)}
                        aria-label={`Удалить сессию ${session.name}`}
                        title="Удалить"
                        className="focus-ring mt-1 rounded px-1 text-sm leading-none text-slate-300 opacity-0 transition-opacity hover:text-slate-600 group-hover:opacity-100"
                      >
                        ×
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </aside>

        <main {...dropHandlers} className={`min-w-0 ${dragging ? "rounded-lg ring-2 ring-blue-300" : ""}`}>
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

          {llmConfigured === false ? (
            <div className="mb-6 border-l-2 border-amber-400 bg-amber-50 px-4 py-3">
              <p className="text-sm font-medium text-amber-900">Ключ OpenRouter не задан</p>
              <p className="mt-1 text-sm text-amber-800">
                Запись расшифруется и обезличится, но ответа модели не будет. Добавьте{" "}
                <span className="font-mono">OPENROUTER_API_KEY</span> в файл <span className="font-mono">.env</span>{" "}
                рядом с приложением и перезапустите его.
              </p>
            </div>
          ) : null}

          {busy && progress ? <ProgressBar pct={progress.pct} message={progress.message} /> : null}

          {error ? (
            <div className="border-l-2 border-red-400 bg-red-50 px-4 py-3">
              <p className="text-sm font-medium text-red-900">Не удалось обработать запись</p>
              <p className="mt-1 text-sm text-red-800">{error}</p>
            </div>
          ) : null}

          {!result && !busy && !error ? (
            <div className="flex min-h-[380px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 px-6 py-12 text-center">
              <Mark className="h-10 w-10" />
              <h2 className="mt-4 max-w-sm text-lg font-semibold tracking-tight text-slate-900">
                Расшифровка встреч, которая не покидает ваш компьютер
              </h2>
              <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
                Запись превращается в транскрипт и протокол. Персональные данные маскируются здесь, в модель уходит
                только обезличенный текст.
              </p>
              <ol className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 font-mono text-[11px] uppercase tracking-[0.12em] text-slate-400">
                <li>01 · Аудио</li>
                <li>02 · Маскирование</li>
                <li>03 · Протокол</li>
              </ol>
              <div className="mt-6">
                <Button onClick={() => inputRef.current?.click()} disabled={busy}>
                  Выбрать аудиофайл
                </Button>
              </div>
              <p className="mt-3 text-xs text-slate-400">WAV, MP3, M4A, OGG — до часа. Или перетащите файл сюда.</p>
            </div>
          ) : null}

          {result && current ? <Document session={current} onAnother={() => inputRef.current?.click()} /> : null}
        </main>
      </div>
    </div>
  );
}
