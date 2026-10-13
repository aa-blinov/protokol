import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  analyseAudio,
  getSettings,
  summarize,
  type AnalysisResult,
  type AnalysisProgress,
  type Session,
  type SettingsState,
  type SummarizeResult,
  getSessions,
  saveSessions,
} from "./api";
import { chipClass, MaskedView } from "./Highlight";
import { Review } from "./Review";
import { Toasts, type Notice } from "./Toast";
import { ComposeGate } from "./ComposeGate";
import { SettingsPanel } from "./Settings";
import { Transcript } from "./Transcript";
import { ActualCostLine, formatCount, humanDuration, pluralRu, useEstimate } from "./SummaryControls";
import { Button, CopyButton, Markdown, ProgressBar, Section } from "./ui";
import {
  ArrowLeft,
  ChevronDown,
  Moon,
  Pencil,
  Plus,
  RefreshCw,
  Settings as SettingsIcon,
  Sun,
  Trash2,
} from "lucide-react";

const PRODUCT_NAME = "Протокол";

const THEME_KEY = "sttshka.theme";

/** Which screen is in front, and what is running behind it.
 *
 *  These are two separate states on purpose. Folding them into one ("stage")
 *  looks simpler and is not: clicking "составить заново" on a finished
 *  document has to leave that document on screen with a progress line under
 *  it, and a single state variable can only express one screen at a time --
 *  so the document vanished mid-wait and the user's place was lost. */
type View = "empty" | "review" | "document";
type Busy = "none" | "analysing" | "summarising";

/** The transcript as copyable text: speaker turns when diarized, else plain. */
function transcriptText(analysis: AnalysisResult): string {
  if (analysis.segments.length === 0) return analysis.transcript;
  return analysis.segments
    .map((segment) => `Спикер ${segment.speaker + 1}: ${segment.text}`)
    .join("\n");
}

function buildReport(session: Session): string {
  const { analysis, summary } = session;
  // Blocks are joined by a blank line and the empties are collapsed: filtering
  // out the nulls alone left a run of blank lines wherever a section was
  // missing, which is most of a document without a summary.
  const blocks = [
    [
      `${PRODUCT_NAME}: расшифровка встречи`,
      `Файл: ${session.name}`,
      `Дата: ${new Date(session.createdAt).toLocaleString("ru-RU")}`,
      `Длительность: ${humanDuration(analysis.duration_sec)}`,
      ...(summary ? [`Модель: ${summary.llm_model}`] : []),
    ],
    ...(summary ? [["ВЫЖИМКА", summary.reply_unmasked]] : []),
    ["РАСШИФРОВКА", transcriptText(analysis)],
    // The substitution table, not the masked text itself: the table is what a
    // reader can check by hand, and the masked copy is the same length as the
    // transcript above it for no added information.
    ...(Object.keys(analysis.entity_map).length
      ? [
          [
            "ЧТО СКРЫТО",
            ...Object.entries(analysis.entity_map).map(([token, value]) => `${token} → ${value}`),
          ],
        ]
      : []),
  ];
  return blocks.map((block) => block.join("\n").trim()).join("\n\n").trim() + "\n";
}

function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
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
  settings,
  preset,
  onPreset,
  onResummarise,
  onOpenSettings,
  busy,
}: {
  session: Session;
  settings: SettingsState;
  preset: string;
  onPreset: (preset: string) => void;
  onResummarise: () => void;
  onOpenSettings: () => void;
  busy: boolean;
}) {
  const { analysis, summary } = session;
  const speakers = useMemo(
    () => new Set(analysis.segments.map((segment) => segment.speaker)).size,
    [analysis.segments],
  );
  const tokens = Object.keys(analysis.entity_map).length;
  const [redoOpen, setRedoOpen] = useState(false);
  /** Which sections the reader has folded away. Reading a long transcript is
   *  the common case and reading the summary is the common case; both should
   *  not cost a scroll past each other every time. */
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const toggle = (key: string) => setFolded((prev) => ({ ...prev, [key]: !prev[key] }));
  /** Count folded sections by their value, not by how many keys the record has.
   *  Toggling a section off leaves its key behind set to false, so counting keys
   *  made the header button say «Развернуть всё» with everything already open —
   *  and clicking it folded instead. */
  const anyFolded = Object.values(folded).some(Boolean);
  const estimate = useEstimate(analysis.masked_text.length, settings.model);
  /** Recordings from before the pipeline was split have no cached analysis, so
   *  a second summary would have nothing to run on. Saying so beats offering a
   *  button that answers "анализ не найден". */
  const canResummarise = analysis.cache_key !== "" && settings.has_key;

  return (
    <article
      onKeyDown={(event) => {
        // Ворота живут внутри документа, поэтому Escape ловится здесь: из
        // родителя до них не дотянуться.
        if (event.key === "Escape" && redoOpen) {
          event.stopPropagation();
          setRedoOpen(false);
        }
      }}
    >
      <header>
        <h2 className="break-words text-2xl font-semibold tracking-tight text-slate-900">{session.name}</h2>
        {/* Metadata is separated by space, not by dots: a row of · reads as
            decoration. The model id is left out entirely — it belongs to the
            settings screen, and "deepseek/deepseek-v4.1-flash" means nothing to
            whoever opens the document. */}
        <p className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-slate-500">
          <span className={summary ? "text-emerald-700" : "text-slate-500"}>
            {summary ? "С выжимкой" : "Только расшифровка"}
          </span>
          <time dateTime={session.createdAt} className="tabular-nums">
            {new Date(session.createdAt).toLocaleString("ru-RU", {
              dateStyle: "short",
              timeStyle: "short",
            })}
          </time>
          <span className="tabular-nums">{humanDuration(analysis.duration_sec)}</span>
          <span>
            {analysis.entities.length}{" "}
            {pluralRu(
              analysis.entities.length,
              "персональных данных",
              "персональных данных",
              "персональных данных",
            )}
          </span>
          {speakers > 1 ? (
            <span>
              {speakers} {pluralRu(speakers, "спикер", "спикера", "спикеров")}
            </span>
          ) : null}
        </p>
        <div className="no-print mt-4 flex flex-wrap items-center gap-4">
          <Button
            variant="ghost"
            onClick={() =>
              downloadText(
                `${session.name.replace(/\.[^.]+$/, "")} (расшифровка).txt`,
                buildReport(session),
              )
            }
          >
            Скачать .txt
          </Button>
          <Button variant="ghost" onClick={() => window.print()}>
            Печать / PDF
          </Button>
          <Button
            variant="ghost"
            onClick={() =>
              setFolded(anyFolded ? {} : { summary: true, transcript: true, masked: true })
            }
          >
            {anyFolded ? "Развернуть всё" : "Свернуть всё"}
          </Button>
        </div>
      </header>

      {/* Size, not how long the model took: recordings summarised before the
          pipeline was split carry no timings, and "0 с на подготовку" reads as
          a measured zero rather than a number nobody wrote down. */}
      <Section
        label="Выжимка"
        collapsed={Boolean(folded.summary)}
        onToggle={() => toggle("summary")}
        collapsedNote={
          summary ? `${formatCount(summary.reply_unmasked.length)} знаков` : "не составлялась"
        }
        meta={summary ? <CopyButton text={summary.reply_unmasked} /> : null}
      >
        {summary ? (
          <>
            <Markdown text={summary.reply_unmasked} />
            <div className="no-print mt-5 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-slate-100 pt-3">
              <button
                onClick={() => setRedoOpen((open) => !open)}
                aria-expanded={redoOpen}
                className="focus-ring flex items-center gap-1.5 rounded text-xs text-blue-700 underline"
              >
                <RefreshCw aria-hidden className="h-3.5 w-3.5" />
                Изменить выжимку
                <ChevronDown
                  aria-hidden
                  className={`h-3.5 w-3.5 transition-transform ${redoOpen ? "rotate-180" : ""}`}
                />
              </button>
              {/* What the last summary actually cost belongs beside the control
                  that would spend again, not in the section label where it
                  competed with the heading for the same band. */}
              <ActualCostLine cost={summary.cost} tokensIn={summary.tokens_in} tokensOut={summary.tokens_out} />
              {redoOpen ? (
                <ComposeGate
                  settings={settings}
                  preset={preset}
                  onPreset={onPreset}
                  estimate={estimate}
                  busy={busy}
                  canRun={canResummarise}
                  runLabel="Составить выжимку"
                  onRun={onResummarise}
                  onOpenSettings={onOpenSettings}
                  onClose={() => setRedoOpen(false)}
                  closeLabel="Оставить как есть"
                />
              ) : null}
            </div>
            <details className="no-print mt-4">
              <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                Что модель увидела вместо имён
              </summary>
              <div className="mt-3 max-w-[68ch] rounded border border-slate-200 bg-slate-50 p-3 text-[13px] leading-6 text-slate-600">
                <MaskedView text={summary.reply} entityMap={analysis.entity_map} />
              </div>
            </details>
          </>
        ) : redoOpen ? (
          <ComposeGate
            settings={settings}
            preset={preset}
            onPreset={onPreset}
            estimate={estimate}
            busy={busy}
            canRun={canResummarise}
            runLabel="Составить выжимку"
            onRun={onResummarise}
            onOpenSettings={onOpenSettings}
            onClose={() => setRedoOpen(false)}
            closeLabel="Оставить только расшифровку"
          />
        ) : (
          <div className="max-w-xl">
            <p className="text-sm text-slate-600">
              Вы остановились на расшифровке. Выжимку не отправляли, деньги не потрачены.
            </p>
            <div className="no-print mt-4 flex flex-wrap items-center gap-4">
              <Button onClick={() => setRedoOpen(true)} disabled={busy}>
                Составить выжимку
              </Button>
              {!canResummarise ? (
                <p className="text-xs text-slate-500">
                  Готовой расшифровки от прошлого раза не осталось, поэтому составить выжимку можно будет
                  только после повторной загрузки файла.
                </p>
              ) : null}
            </div>
          </div>
        )}
      </Section>

      <Section
        label="Расшифровка"
        meta={<CopyButton text={transcriptText(analysis)} />}
        collapsed={Boolean(folded.transcript)}
        onToggle={() => toggle("transcript")}
        collapsedNote={`${formatCount(transcriptText(analysis).length)} знаков, ${speakers > 1 ? `${speakers} спикеров` : "один голос"}`}
      >
        <Transcript analysis={analysis} />
      </Section>

      <Section
        label="Что уходит в модель"
        collapsed={Boolean(folded.masked)}
        onToggle={() => toggle("masked")}
        collapsedNote={`${formatCount(analysis.masked_text.length)} знаков, ${tokens} ${pluralRu(tokens, "подстановка", "подстановки", "подстановок")}`}
      >
        {/* One level of folding, not two. The section already collapses; a
            separate "показать целиком" inside it meant three states for what is
            really one decision. */}
        <div className="max-h-[30rem] max-w-[68ch] overflow-y-auto text-[15px] leading-7 text-slate-800">
          <MaskedView text={analysis.masked_text} entityMap={analysis.entity_map} />
        </div>

        {tokens > 0 ? (
          <details className="no-print mt-4">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
              Таблица подстановок
            </summary>
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {Object.entries(analysis.entity_map).map(([token, value]) => (
                <li key={token} className="flex items-baseline gap-2 text-xs">
                  <span className={chipClass(token.replace(/_\d+$/, ""))}>{token}</span>
                  <span className="font-mono text-slate-600">{value}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </Section>
    </article>
  );
}

/** The panel under "составить заново".
 *
 *  The point is stated in the first line: the recording does not get listened
 *  to again. Without that, a second summary reads as a second full run, and the
 *  cost line beside the button would look like it applies to both. */

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [current, setCurrent] = useState<Session | null>(null);
  const [view, setView] = useState<View>("empty");
  const [busy, setBusy] = useState<Busy>("none");
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Shown over the page, so a failure cannot hide behind a scrolled document. */
  const [notices, setNotices] = useState<Notice[]>([]);
  const [dragging, setDragging] = useState(false);
  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [preset, setPreset] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  /** Откуда открыли настройки: из пустого экрана, из истории или из протокола. */
  const [settingsFrom, setSettingsFrom] = useState<"empty" | "document">("empty");
  /** Seconds each stage took last time, keyed by stage name. The progress line
   *  turns them into "осталось примерно N с" -- honest, because the estimate
   *  comes from this machine's own earlier runs rather than a guess. */
  const stageTimings = useRef<Record<string, number>>({});
  const [eta, setEta] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  /** Row awaiting a delete confirmation. Removing a transcript is destructive
   *  and cannot be undone, so it takes a second, deliberate click. */
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  /** Name of the file currently being worked on, so the progress bar can say
   *  which recording it belongs to; without it the bar sits above a finished
   *  document and the two get confused. */
  const [workingOn, setWorkingOn] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light",
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const viewRef = useRef<View>(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);
  const listRef = useRef<HTMLUListElement>(null);

  // A ticking clock for the current run. Ticks once a second, which is also
  // the resolution any human reading "прошло 43 с" cares about.
  useEffect(() => {
    if (busy === "none") {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const tick = () => setElapsed(Math.round((Date.now() - started) / 1000));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    void getSessions().then(setSessions).catch(() => setSessions([]));
  }, []);


  useEffect(() => {
    if (!sessions.length) return;
    void saveSessions(sessions).catch(() => undefined);
  }, [sessions]);

  // Escape closes whatever is open, ⌘O picks a file. Without these the loop
  // "drop a file, wait, read it, repeat" runs entirely on the mouse, and the
  // settings panel has no keyboard route out.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (settingsOpen) setSettingsOpen(false);
        else if (confirmDeleteId) setConfirmDeleteId(null);
        else if (query) setQuery("");
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "o") {
        event.preventDefault();
        // `busy` is state, so the effect can read it directly instead of
        // closing over a derived binding that does not exist yet.
        if (busy === "none") inputRef.current?.click();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [settingsOpen, query, busy, confirmDeleteId]);

  // The model and the focus come from the saved settings, not from constants:
  // the dialog is the only place they are chosen, so starting with hardcoded
  // values would silently override whatever the user picked.
  useEffect(() => {
    getSettings()
      .then((loaded) => {
        setSettings(loaded);
        setPreset(loaded.preset);
      })
      .catch(() => setSettings(null));
  }, []);

  /** Drop a file: transcribe, mask, then stop and show what would be sent. */
  const analyse = useCallback(async (file: File) => {
    const previousView = viewRef.current;
    setError(null);
    setWorkingOn(file.name);
    setBusy("analysing");
    // Возврат к экрану разбора нужен сразу. Оба его состояния — идущий разбор
    // и пустой экран — отрисованы только при view === "empty". Когда новый файл
    // выбирают из документа, view оставался "document" весь разбор, и человек
    // видел старый протокол до самой секунды появления выжимки.
    setView("empty");
    setProgress({ stage: "transcribe", pct: 0, message: "Загрузка файла" });
    try {
      const result: AnalysisResult = await analyseAudio(file, (event) => {
        setProgress(event);
        const known = stageTimings.current[event.stage];
        setEta(known !== undefined ? known * (1 - event.pct / 100) : null);
      });
      const session: Session = {
        id: crypto.randomUUID(),
        name: file.name,
        createdAt: new Date().toISOString(),
        analysis: result,
        summary: null,
      };
      setSessions((previous) => [session, ...previous].slice(0, 50));
      setCurrent(session);
      // Remembered only on success: a failed run has no timings to learn from.
      if (result.timings) stageTimings.current = { ...stageTimings.current, ...result.timings };
      setView("review");
    } catch (caught) {
      // The failed file is not the session on screen — drop that stale result,
      // otherwise the error reads as belonging to the document below it.
      fail(caught instanceof Error ? caught.message : String(caught));
      // Неудавшийся файл к открытому документу отношения не имеет: возвращаемся
      // туда, откуда начали, иначе человек теряет место без причины.
      setView(previousView);
    } finally {
      setBusy("none");
      setProgress(null);
      setWorkingOn(null);
      setEta(null);
    }
  }, []);

  /** Ask for the summary over the analysis already in hand. */
  const runSummary = useCallback(
    async (session: Session) => {
      if (!settings) return;
      setError(null);
      setBusy("summarising");
      setWorkingOn(session.name);
      try {
        const result: SummarizeResult = await summarize(
          session.analysis.cache_key,
          settings.model,
          preset || settings.preset,
          null,
          // Sent with the request because the analysis cache holds eight
          // recordings: without it, re-summarising anything older answers
          // "загрузите заново" about a file that is still right there.
          session.analysis.masked_text,
        );
        setSessions((previous) =>
          previous.map((item) => (item.id === session.id ? { ...item, summary: result } : item)),
        );
        setCurrent((active) => (active?.id === session.id ? { ...active, summary: result } : active));
        // A summary means there is something to read, so land on the document.
        setView("document");
      } catch (caught) {
        fail(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy("none");
        setWorkingOn(null);
      }
    },
    [settings, preset],
  );

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    // Dropping a second file mid-run started a parallel transcription whose
    // result then replaced the first one's session. Better to ignore it: the
    // run in progress already owns the screen.
    if (busy !== "none") return;
    const file = event.dataTransfer.files?.[0];
    if (file) void analyse(file);
  };

  // A single onDragLeave is not enough here. It fires again every time the
  // cursor crosses onto a child element, and when a file is pulled straight out
  // of the window it never fires at all -- which left the drop ring painted over
  // the content with no way to clear it. Counting enter/leave pairs fixes both
  // the flicker and the stuck state.
  const dropHandlers = {
    onDragEnter: (event: React.DragEvent) => {
      event.preventDefault();
      dragDepth.current += 1;
      setDragging(true);
    },
    onDragOver: (event: React.DragEvent) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    },
    onDragLeave: (event: React.DragEvent) => {
      event.preventDefault();
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragging(false);
    },
    onDrop,
  };

  const dismissNotice = useCallback((id: string) => {
    setNotices((previous) => previous.filter((item) => item.id !== id));
  }, []);

  const notice = useCallback(
    (tone: Notice["tone"], text: string) => {
      const id = crypto.randomUUID();
      setNotices((previous) => [...previous, { id, tone, text }]);
      // Errors stay until dismissed: a failure that quietly disappears is the
      // same failure the person could not find in the first place.
      if (tone === "good") window.setTimeout(() => dismissNotice(id), 5000);
    },
    [dismissNotice],
  );

  /** Every failure goes through here. The in-flow banner stays as the record;
   *  the toast is what someone scrolled to the bottom of a document can see. */
  const fail = useCallback(
    (text: string) => {
      setError(text);
      notice("bad", text);
    },
    [notice],
  );

  const openSettings = () => {
    setSettingsFrom(view === "document" && current ? "document" : "empty");
    setSettingsOpen(true);
  };

  const removeSession = (id: string) => {
    setSessions((previous) => previous.filter((session) => session.id !== id));
    setCurrent((active) => (active?.id === id ? null : active));
  };

  const renameSession = (id: string, name: string) => {
    const trimmed = name.trim();
    setSessions((previous) =>
      previous.map((session) =>
        session.id === id ? { ...session, name: trimmed || session.name } : session,
      ),
    );
    setEditingId(null);
  };

  const visibleSessions = query
    ? sessions.filter((session) => session.name.toLowerCase().includes(query.trim().toLowerCase()))
    : sessions;
  // Смена экрана должна возвращать к началу. Иначе: читаете длинный протокол,
  // жмёте «Новая запись», выбираете файл — контент наверху меняется, а
  // прокрутка остаётся там, где была, и кажется, что ничего не произошло.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [view, busy === "analysing"]);

  // Открытая запись всегда должна быть в поле зрения: переход к ней может
  // прийти не из списка, и прокручивать его руками не должен никто.
  useEffect(() => {
    if (!current) return;
    listRef.current
      ?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }, [current, visibleSessions]);

  const showDocument = view === "document" && current !== null;
  const showReview = view === "review" && current !== null;

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
              {theme === "dark" ? (
                <Sun aria-hidden className="h-4 w-4" />
              ) : (
                <Moon aria-hidden className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-5xl grid-cols-1 gap-x-10 gap-y-8 px-6 py-8 lg:grid-cols-[200px_1fr] print:grid-cols-1">
        <aside className="no-print order-2 self-start lg:order-1">
          {/* The collection owns "new". A header action inside one document is
              object-scoped by convention and cannot be found from any other
              screen, so the only reliable place for the app's primary action is
              here, where it is always in the same spot. */}
          <Button onClick={() => inputRef.current?.click()} disabled={busy !== "none"} className="w-full">
            <Plus aria-hidden className="h-4 w-4" />
            Новая запись
          </Button>
          <h2 className="mt-7 font-mono text-[12px] font-medium uppercase tracking-[0.12em] text-slate-500">
            История
          </h2>
          {sessions.length > 0 ? (
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Поиск"
              aria-label="Поиск по истории"
              className="focus-ring mt-3 w-full rounded border border-slate-200 bg-white px-2 py-1 text-sm placeholder:text-slate-500"
            />
          ) : null}
          {sessions.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">Здесь появятся обработанные записи</p>
          ) : visibleSessions.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">Нет записей с таким названием</p>
          ) : (
            <ul
              ref={listRef}
              aria-label="Обработанные записи"
              className="mt-2 space-y-0.5"
              onKeyDown={(event) => {
                const items = Array.from(
                  listRef.current?.querySelectorAll<HTMLElement>("[data-item]") ?? [],
                );
                // Фокус стоит на кнопке внутри строки, а items — это сами строки,
                // поэтому индекс ищем у ближайшего предка: иначе он всегда -1 и
                // ни стрелка, ни F2, ни Delete не срабатывают.
                const at = items.indexOf(
                  (document.activeElement as HTMLElement)?.closest<HTMLElement>("[data-item]") ??
                    (null as never),
                );
                // Фокусируем кнопку внутри строки, а не саму строку: <li> не
                // фокусируем, и вызов focus() на нём молча ничего не делает.
                const stepTo = (index: number) =>
                  items[index]?.querySelector<HTMLElement>("button")?.focus();
                if (event.key === "ArrowDown" && at > -1 && at < items.length - 1) {
                  event.preventDefault();
                  stepTo(at + 1);
                } else if (event.key === "ArrowUp" && at > 0) {
                  event.preventDefault();
                  stepTo(at - 1);
                } else if (event.key === "F2" && at > -1) {
                  event.preventDefault();
                  setEditingId(items[at].dataset.id ?? null);
                  setDraft(items[at].dataset.name ?? "");
                } else if ((event.key === "Delete" || event.key === "Backspace") && at > -1) {
                  event.preventDefault();
                  setConfirmDeleteId(items[at].dataset.id ?? null);
                }
              }}
            >
              {visibleSessions.map((session) => (
                <li
                  key={session.id}
                  data-item
                  data-id={session.id}
                  data-name={session.name}
                  data-active={current?.id === session.id && !showReview}
                  className="group flex items-start"
                >
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
                        onClick={() => {
                          setCurrent(session);
                          setView("document");
                          setError(null);
                        }}
                        className={`focus-ring min-w-0 flex-1 rounded px-2 py-1 text-left transition-colors ${
                          current?.id === session.id && !showReview
                            ? "bg-slate-100 text-blue-700"
                            : "text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        <span className="block truncate text-sm">{session.name}</span>
                        {/* PII count, plus whether a summary exists: the list is
                            for finding a recording fast, and "does this one have
                            the answer or only the text" is worth knowing there. */}
                        <span className="block truncate text-[12px] tabular-nums text-slate-500">
                          {/* JSX drops a newline between expressions, so the
                              separator has to be written out or the row reads
                              "выжимка5 персональных данных". */}
                          {session.summary ? "выжимка" : "без выжимки"},{" "}
                          {session.analysis.entities.length}{" "}
                          {pluralRu(
                            session.analysis.entities.length,
                            "персональных данных",
                            "персональных данных",
                            "персональных данных",
                          )}
                        </span>
                      </button>
                      <button
                        onClick={() => {
                          setEditingId(session.id);
                          setDraft(session.name);
                        }}
                        aria-label={`Переименовать запись ${session.name}`}
                        title="Переименовать"
                        className="focus-ring grid h-7 w-7 shrink-0 place-items-center rounded text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:text-slate-700"
                      >
                        <Pencil aria-hidden className="h-4 w-4" />
                      </button>
                      {confirmDeleteId === session.id ? (
                        <span className="mt-1 flex items-center gap-1">
                          <button
                            onClick={() => {
                              removeSession(session.id);
                              setConfirmDeleteId(null);
                            }}
                            className="focus-ring rounded px-1.5 py-0.5 text-xs text-red-700 hover:bg-red-50"
                          >
                            Удалить
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="focus-ring rounded px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
                          >
                            Нет
                          </button>
                        </span>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(session.id)}
                          aria-label={`Удалить запись ${session.name}`}
                          title="Удалить запись"
                          className="focus-ring grid h-7 w-7 shrink-0 place-items-center rounded text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:text-slate-700"
                        >
                          <Trash2 aria-hidden className="h-4 w-4" />
                        </button>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-8 border-t border-slate-200 pt-3">
            <button
              onClick={() => (settingsOpen ? setSettingsOpen(false) : openSettings())}
              aria-expanded={settingsOpen}
              aria-controls="settings-panel"
              className={`focus-ring flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors ${
                settingsOpen ? "bg-slate-100 text-blue-700" : "text-slate-600 hover:bg-slate-50"
              }`}
            >
              <SettingsIcon aria-hidden className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">Настройки</span>
            </button>
          </div>
        </aside>

        <main {...dropHandlers} className={`order-1 min-w-0 lg:order-2 ${dragging ? "rounded-lg ring-2 ring-blue-300" : ""}`}>
          <input
            ref={inputRef}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.mp4"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file && busy === "none") void analyse(file);
            }}
          />

          {settingsOpen ? (
            <section id="settings-panel" aria-label="Настройки" className="max-w-2xl">
              {/* Назад — слева и над заголовком, как в браузере, почте и любом
                  мастере настроек. Кнопка в правом углу читалась как ещё одно
                  действие рядом с формой, а навигация должна читаться как
                  навигация: мелко, приглушённо, над тем, куда возвращают. */}
              <button
                onClick={() => setSettingsOpen(false)}
                aria-label={settingsFrom === "document" ? "Вернуться к протоколу" : "Вернуться к записям"}
                className="focus-ring -ml-1 mb-3 inline-flex items-center gap-1.5 rounded text-sm text-slate-500 hover:text-slate-900"
              >
                <ArrowLeft aria-hidden className="h-4 w-4" />
                {settingsFrom === "document" ? "К протоколу" : "К записям"}
              </button>
              <h2 className="text-lg font-semibold tracking-tight text-slate-900">Настройки</h2>
              <p className="mt-1 text-sm text-slate-600">
                Здесь выбирается сервис, который составит выжимку, и ключ к нему. Всё хранится на этом
                компьютере.
              </p>
              <SettingsPanel
                onSaved={(saved) => {
                  setSettings(saved);
                  // Saving from the dialog is an explicit choice of focus, so
                  // it becomes the default everywhere -- including on a review
                  // screen that is open with a different one selected. The
                  // review screen's own picker stays a per-run override.
                  setPreset(saved.preset);
                }}
              />
            </section>
          ) : null}

          {!settingsOpen && settings && !settings.has_key && view === "empty" ? (
            <div className="mb-6 border-l-2 border-red-400 bg-red-50 px-4 py-3">
              <p className="text-sm font-medium text-red-900">Не задан ключ</p>
              <p className="mt-1 text-sm text-red-800">
                Запись всё равно расшифруется и личные данные будут скрыты, но ответа модели не будет. Откройте{" "}
                <button onClick={openSettings} className="font-medium underline">
                  «Настройки»
                </button>{" "}
                в левой панели и вставьте ключ.
              </p>
            </div>
          ) : null}

          {!settingsOpen && busy && progress ? (
            <div>
              <ProgressBar pct={progress.pct} message={progress.message} eta={eta} elapsed={elapsed} />
              {/* Only when a document is behind the bar. On a fresh run the
                  working panel below already names the file. */}
              {workingOn && view !== "empty" ? (
                <p className="mt-1 truncate font-mono text-[12px] text-slate-600">{workingOn}</p>
              ) : null}
            </div>
          ) : null}

          {/* Summarising has no stream of its own -- one provider call, one wait --
              so the bar is given a stage name of its own rather than reusing the
              transcription line, which would name the wrong thing. */}
          {!settingsOpen && busy === "summarising" ? (
            <div>
              <ProgressBar pct={70} message="Модель читает текст и пишет выжимку" elapsed={elapsed} />
              {workingOn ? <p className="mt-1 truncate font-mono text-[12px] text-slate-600">{workingOn}</p> : null}
            </div>
          ) : null}

          {!settingsOpen && error ? (
            <div className="border-l-2 border-red-400 bg-red-50 px-4 py-3" role="status">
              <p className="text-sm font-medium text-red-900">Не получилось</p>
              <p className="mt-1 text-sm text-red-800">{error}</p>
            </div>
          ) : null}

          {!settingsOpen && view === "empty" && !error && busy !== "analysing" ? (
            <div className="no-print flex min-h-[380px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 px-6 py-12 text-center">
              <Mark className="h-10 w-10" />
              <h2 className="mt-4 max-w-sm text-lg font-semibold tracking-tight text-slate-900">
                Загрузите запись встречи
              </h2>
              {/* The action sits above the prose, not below two paragraphs of it.
                  One line says what comes back; one line carries the promise that
                  makes this tool different from sending the file to a service. */}
              <div className="mt-5">
                <Button onClick={() => inputRef.current?.click()} disabled={busy !== "none"} size="lg">
                  Выбрать аудиофайл
                </Button>
              </div>
              {/* One line, and only what answers a question the button cannot.
                  Drag-and-drop is invisible until you know it exists; the privacy
                  promise is not answered here — it is shown, later, on the review
                  screen, where the masked text is actually there to read. */}
              <p className="mx-auto mt-3 max-w-md text-sm text-slate-500">
                Или перетащите сюда. Подойдёт почти любой формат
              </p>
            </div>
          ) : null}

          {!settingsOpen && view === "empty" && busy === "analysing" ? (
            <div className="no-print flex min-h-[380px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 px-6 py-12 text-center">
              <Mark className="h-10 w-10" />
              <h2 className="mt-4 max-w-sm text-lg font-semibold tracking-tight text-slate-900">
                Обрабатываем запись
              </h2>
              {workingOn ? (
                <p className="mt-2 max-w-sm truncate font-mono text-xs text-slate-500">{workingOn}</p>
              ) : null}
              <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">
                Пока идёт разбор, первые минуты уходят на чтение. Это самая долгая часть.
              </p>
            </div>
          ) : null}

          {!settingsOpen && showReview && settings ? (
            <Review
              name={current.name}
              analysis={current.analysis}
              settings={settings}
              preset={preset || settings.preset}
              onPreset={setPreset}
              onSend={() => void runSummary(current)}
              onSkip={() => setView("document")}
              onOpenSettings={openSettings}
              busy={busy === "summarising"}
            />
          ) : null}

          {!settingsOpen && showDocument && settings ? (
            <Document
              session={current}
              settings={settings}
              preset={preset}
              onPreset={setPreset}
              onResummarise={() => void runSummary(current)}
              onOpenSettings={openSettings}
              busy={busy === "summarising"}
            />
          ) : null}
        </main>
      </div>
      <Toasts notices={notices} onDismiss={dismissNotice} />
    </div>
  );
}