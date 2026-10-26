import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
import { chipClass, findHits, MaskedView } from "./Highlight";
import { Review } from "./Review";
import { Toasts, type Notice } from "./Toast";
import { ComposeGate } from "./ComposeGate";
import { SettingsPanel } from "./Settings";
import { Transcript, TranscriptSearch } from "./Transcript";
import { ActualCostLine, formatCount, humanDuration, pluralRu, useEstimate } from "./SummaryControls";
import { Button, CopyButton, FIELD, Markdown, ProgressBar, Section } from "./ui";
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

function buildReport(session: Session, labels: Record<string, string>): string {
  const { analysis, summaries } = session;
  const made = Object.entries(summaries);
  // Blocks are joined by a blank line and the empties are collapsed: filtering
  // out the nulls alone left a run of blank lines wherever a section was
  // missing, which is most of a document without a summary.
  const blocks = [
    [
      `${PRODUCT_NAME}: расшифровка встречи`,
      `Файл: ${session.name}`,
      `Дата: ${new Date(session.createdAt).toLocaleString("ru-RU")}`,
      `Длительность: ${humanDuration(analysis.duration_sec)}`,
      ...(made.length
        ? [`Модель: ${[...new Set(made.map(([, s]) => s.llm_model))].join(", ")}`]
        : []),
    ],
    // Every summary, each under its own mode. Picking one would leave the rest
    // out of the file, and this file is the artefact that goes to someone else.
    ...made.map(([mode, s]) => [`ВЫЖИМКА: ${labels[mode] ?? mode}`, s.reply_unmasked]),
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

/** The product mark: a page with one line redacted. Same shape as the app icon and favicon. */
function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label={PRODUCT_NAME}>
      <rect width="32" height="32" rx="7" fill="#1f5a46" />
      <rect x="8" y="6" width="16" height="20" rx="2" fill="#faf8f3" />
      <rect x="11" y="11" width="10" height="2" rx="1" fill="#a29b8a" />
      <rect x="11" y="15" width="7" height="2" rx="1" fill="#a29b8a" />
      <rect x="11" y="19" width="10" height="3" rx="0.5" fill="#10332a" />
    </svg>
  );
}

/** The raised document: file header, then the pipeline sections. */
function Document({
  session,
  settings,
  preset,
  mode,
  onMode,
  onPreset,
  onResummarise,
  onOpenSettings,
  busy,
}: {
  session: Session;
  settings: SettingsState;
  /** The mode the compose form will run next. Choosing it does not change the summary on screen. */
  preset: string;
  /** The mode whose summary is on screen, picked with the mode chips. */
  mode: string | null;
  onMode: (mode: string) => void;
  onPreset: (preset: string) => void;
  /** Resolves true when the summary was made, so the compose form can close. */
  onResummarise: () => Promise<boolean>;
  onOpenSettings: () => void;
  busy: boolean;
}) {
  const { analysis, summaries } = session;
  /** Modes that already have one, so moving between them costs no call. */
  const made = Object.keys(summaries);
  /** The mode on screen: the one the reader picked, else the settings' mode if it has a summary,
   *  else the latest one made. Choosing a mode in the compose form never changes it. */
  const shown = mode && made.includes(mode) ? mode : made.includes(preset) ? preset : (made[made.length - 1] ?? preset);
  /** The summary of the mode on screen. It disappears only when that mode is left unmade. */
  const summary = summaries[shown] ?? null;
  const speakers = useMemo(
    () => new Set(analysis.segments.map((segment) => segment.speaker)).size,
    [analysis.segments],
  );
  const tokens = Object.keys(analysis.entity_map).length;
  const [redoOpen, setRedoOpen] = useState(false);
  /** Which sections the reader has folded away. Reading a long transcript is
   *  the common case and reading the summary is the common case; both should
   *  not cost a scroll past each other every time.
   *
   *  The masked text starts folded: it is the part a reader verifies rather
   *  than reads, the section says how much is in there, and the arrow opens it
   *  in one click if the checking matters today. */
  const [folded, setFolded] = useState<Record<string, boolean>>({ masked: true });
  /* Search lives here, not inside the transcript section: folding that section
     unmounts whatever is in it, and a search that folds away with the text it
     searches for is no search at all. */
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const hits = useMemo(
    () => findHits(analysis.transcript, query),
    [analysis.transcript, query],
  );
  // Reset on a new query and on a different recording: the second leaves the
  // cursor pointing past the end of a shorter list.
  useEffect(() => setCursor(0), [query, analysis.transcript]);
  const step = (direction: 1 | -1) =>
    setCursor((index) => (index + direction + hits.length) % hits.length);

  // Enter walks the matches from anywhere on the page, not only while the field
  // has focus: the point of the search is to stop looking at the input and read.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || !hits.length) return;
      if (event.target instanceof HTMLInputElement) return;
      event.preventDefault();
      setCursor((index) => (index + (event.shiftKey ? -1 : 1) + hits.length) % hits.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hits.length]);
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
  // Not `cache_key`: recordings analysed before the pipeline was split have
  // none and never will, yet their masked text is in the session file and the
  // endpoint reads it from there. Gating on the cache meant those recordings
  // could only be summarised again by re-uploading and re-transcribing.
  const canResummarise = analysis.masked_text.trim() !== "" && settings.has_key;

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
        <h2 className="break-words text-2xl font-semibold tracking-tight text-stone-900">{session.name}</h2>
        {/* Metadata is separated by space, not by dots: a row of · reads as
            decoration. The model id is left out entirely — it belongs to the
            settings screen, and "deepseek/deepseek-v4.1-flash" means nothing to
            whoever opens the document. */}
        <p className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-stone-500">
          <span className={summary ? "text-accent-700" : "text-stone-500"}>
            {made.length
              ? summary
                ? "С выжимкой"
                : // There are summaries, just not for the mode on screen. Saying
                  // «только расшифровка» here would be a lie the reader has no
                  // way to disprove without opening every other mode.
                  "Выжимка в другом режиме"
              : "Только расшифровка"}
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
      </header>

      {/* Outside the document header on purpose: a sticky element travels only
          inside its own parent, and the header is 119 px tall — the bar would
          have stuck for 119 px and then scrolled away exactly as before. */}
      <div style={{ top: "var(--header-h, 69px)" }} className="no-print sticky z-[5] flex flex-wrap items-center gap-4 border-b border-stone-100 bg-paper py-3">
        {/* Pinned under the app header. A document is thirteen screens tall at
            half an hour, and a query you cannot change without scrolling back
            to the top is a query you only get to type once. Its top is the
            header's measured height, written to --header-h by App at runtime: the header
            follows its buttons, and it has already moved once. The header is z-10, so this
            sits below it. Padding rather than margin, because a margin scrolls away
            under a stuck element and leaves a gap content shows through.

            bg-paper, not bg-sheet: the page is stone-100, so a white bar cut a
            pale strip across the document. bg-paper is the same colour the body
            is painted with, in both themes, which is what a sticky element has
            to be — the colour of whatever it covers. */}
        {/* Transcript renders its search here. In the section body it folded
            away with the section, and searching meant unfolding a dozen
            screens of text first. */}
        <div className="min-w-[13rem] flex-1">
          <TranscriptSearch
            query={query}
            hits={hits}
            cursor={cursor}
            onQuery={setQuery}
            onStep={step}
          />
        </div>
        {/* min-h-[38px] to match the field beside it: at 36 the buttons
            centre inside the row and their borders sit a pixel off the search
            box, which reads as a mis-drawn frame even though both borders are
            the same colour. */}
        {settings.policy?.allow_export === false ? null : (
        <>
        <Button
          variant="ghost"
          className="min-h-[38px]"
          onClick={() =>
            downloadText(
              `${session.name.replace(/\.[^.]+$/, "")} (расшифровка).txt`,
              buildReport(
                session,
                Object.fromEntries(settings.presets.map((item) => [item.key, item.label])),
              ),
            )
          }
        >
          Скачать .txt
        </Button>
        <Button variant="ghost" className="min-h-[38px]" onClick={() => window.print()}>
          Печать / PDF
        </Button>
        </>
        )}
        <Button
          variant="ghost"
          className="min-h-[38px]"
          onClick={() =>
            setFolded(anyFolded ? {} : { summary: true, transcript: true, masked: true })
          }
        >
          {anyFolded ? "Развернуть всё" : "Свернуть всё"}
        </Button>
      </div>

      {/* Size, not how long the model took: recordings summarised before the
          pipeline was split carry no timings, and "0 с на подготовку" reads as
          a measured zero rather than a number nobody wrote down. */}
      <Section
        label="Выжимка"
        collapsed={Boolean(folded.summary)}
        onToggle={() => toggle("summary")}
        collapsedNote={
          summary
            ? `${formatCount(summary.reply_unmasked.length)} знаков`
            : made.length
              ? `составлена в другом режиме, вариантов: ${made.length}`
              : "не составлялась"
        }
        meta={summary && settings.policy?.allow_export !== false ? <CopyButton text={summary.reply_unmasked} /> : null}
      >
        {/* One chip per mode, so every summary stays reachable: a made mode shows its
            own result, an unmade one opens the compose form for that mode. The form
            does not change what is on screen until its summary exists. Out here
            rather than under the summary, because the mode on screen is often the
            one that has not been made yet. */}
        {settings.presets.length > 0 ? (
          <div className="no-print mb-5 flex flex-wrap items-center gap-2">
            <span className="text-xs text-stone-500">Выжимки по режимам:</span>
            {settings.presets.map((item) => {
              const done = made.includes(item.key);
              const active = item.key === shown;
              return (
                <button
                  key={item.key}
                  onClick={() => {
                    if (done) {
                      onMode(item.key);
                    } else {
                      onPreset(item.key);
                      setRedoOpen(true);
                    }
                  }}
                  aria-current={active}
                  title={done ? undefined : "Выжимка в этом режиме ещё не составлена"}
                  className={
                    active
                      ? "focus-ring rounded-full border border-accent-700 bg-accent-50 px-3 py-1 text-xs text-accent-800"
                      : done
                        ? "focus-ring rounded-full border border-stone-300 px-3 py-1 text-xs text-stone-600 hover:bg-stone-50"
                        : "focus-ring rounded-full border border-dashed border-stone-300 px-3 py-1 text-xs text-stone-500 hover:bg-stone-50"
                  }
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        ) : null}
        {summary ? (
          <>
            {summary.warnings?.length ? (
              <ul className="mb-4 space-y-1 border border-stone-300 bg-stone-50 px-3 py-2 text-sm text-stone-700">
                {summary.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <Markdown text={summary.reply_unmasked} />
            <div className="no-print mt-5 flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-stone-100 pt-3">
              <button
                onClick={() => setRedoOpen((open) => !open)}
                aria-expanded={redoOpen}
                className="focus-ring flex items-center gap-1.5 rounded text-xs text-accent-700 underline"
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
                  onRun={async () => {
                    if (await onResummarise()) setRedoOpen(false);
                  }}
                  onOpenSettings={onOpenSettings}
                  onClose={() => setRedoOpen(false)}
                  closeLabel="Оставить как есть"
                />
              ) : null}
            </div>
            <details className="no-print mt-4">
              <summary className="cursor-pointer text-xs text-stone-500 hover:text-stone-700">
                Что модель увидела вместо имён
              </summary>
              <div className="mt-3 max-w-[68ch] rounded border border-stone-200 bg-stone-50 p-3 text-[13px] leading-6 text-stone-600">
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
            onRun={async () => {
              if (await onResummarise()) setRedoOpen(false);
            }}
            onOpenSettings={onOpenSettings}
            onClose={() => setRedoOpen(false)}
            closeLabel="Оставить только расшифровку"
          />
        ) : (
          <div className="max-w-xl">
            <p className="text-sm text-stone-600">
              Вы остановились на расшифровке. Выжимку не отправляли, деньги не потрачены.
            </p>
            <div className="no-print mt-4 flex flex-wrap items-center gap-4">
              <Button onClick={() => setRedoOpen(true)} disabled={busy}>
                Составить выжимку
              </Button>
              {!canResummarise ? (
                <p className="text-xs text-stone-500">
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
        meta={settings.policy?.allow_export === false ? null : <CopyButton text={transcriptText(analysis)} />}
        collapsed={Boolean(folded.transcript) && query.trim() === ""}
        onToggle={() => toggle("transcript")}
        collapsedNote={`${formatCount(transcriptText(analysis).length)} знаков, ${speakers > 1 ? `${speakers} спикеров` : "один голос"}`}
      >
        <Transcript analysis={analysis} query={query} hits={hits} cursor={cursor} />
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
        <div className="max-h-[30rem] max-w-[68ch] overflow-y-auto text-[15px] leading-7 text-stone-800">
          <MaskedView text={analysis.masked_text} entityMap={analysis.entity_map} />
        </div>

        {tokens > 0 ? (
          <details className="no-print mt-4">
            <summary className="cursor-pointer text-xs text-stone-500 hover:text-stone-700">
              Таблица подстановок
            </summary>
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {Object.entries(analysis.entity_map).map(([token, value]) => (
                <li key={token} className="flex items-baseline gap-2 text-xs">
                  <span className={chipClass(token.replace(/_\d+$/, ""))}>{token}</span>
                  <span className="font-mono text-stone-600">{value}</span>
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
  /** The mode whose summary is on screen for the open recording; null means the default choice. */
  const [shownMode, setShownMode] = useState<string | null>(null);
  // Another recording starts from its own default, not from the mode last looked at.
  useEffect(() => setShownMode(null), [current?.id]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  /** Откуда открыли настройки: из пустого экрана, из истории или из протокола. */
  const [settingsFrom, setSettingsFrom] = useState<"empty" | "document">("empty");
  /** Seconds each stage took last time, keyed by stage name. The progress line
   *  turns them into "осталось примерно N с" -- honest, because the estimate
   *  comes from this machine's own earlier runs rather than a guess. */
  const stageTimings = useRef<Record<string, number>>({});
  const [eta, setEta] = useState<number | null>(null);
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
  // The bar under the header sticks at the header's bottom edge. The edge is measured, not
  // assumed: the header follows its buttons and title, and it has already moved from 77 px to 69 px.
  const headerRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const header = headerRef.current;
    if (!header) return;
    const measure = () =>
      document.documentElement.style.setProperty("--header-h", `${header.getBoundingClientRect().height}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    return () => observer.disconnect();
  }, []);
  const dragDepth = useRef(0);
  const viewRef = useRef<View>(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);
  const listRef = useRef<HTMLUListElement>(null);

  // When the current run started. The clock that shows it ticks inside ProgressBar,
  // so the rest of the screen does not re-render once a second.
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null);
  useEffect(() => {
    setRunStartedAt(busy === "none" ? null : Date.now());
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
        summaries: {},
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
      if (!settings) return false;
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
          session.analysis.entity_map,
        );
        // Filed under the mode it was made in, so making a second summary never
        // replaces the first. This is the whole point: switching the mode used
        // to overwrite what was already there.
        const filed: Session = {
          ...session,
          summaries: { ...session.summaries, [result.preset ?? preset]: result },
        };
        setSessions((previous) => previous.map((item) => (item.id === session.id ? filed : item)));
        // The screen moves to the summary just made; the others stay under their own chips.
        setShownMode(result.preset ?? preset);
        setCurrent((active) => (active?.id === session.id ? filed : active));
        // A summary means there is something to read, so land on the document.
        setView("document");
        // Tells the caller the summary is made, so its compose form can close.
        return true;
      } catch (caught) {
        fail(caught instanceof Error ? caught.message : String(caught));
        return false;
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
      // The same message twice is one toast: a repeated click on a failing button
      // must not stack identical boxes at the bottom of the screen.
      setNotices((previous) =>
        previous.some((item) => item.tone === tone && item.text === text)
          ? previous
          : [...previous, { id, tone, text }],
      );
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
      <header ref={headerRef} className="no-print sticky top-0 z-10 border-b border-stone-200 bg-sheet">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <Mark className="h-7 w-7 shrink-0" />
          <div className="min-w-0">
            <h1 className="text-lg font-semibold tracking-tight text-stone-900">{PRODUCT_NAME}</h1>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              onClick={() => inputRef.current?.click()}
              disabled={busy !== "none"}
              ariaLabel="Новая запись"
              className="gap-1.5"
            >
              <Plus aria-hidden className="h-4 w-4" />
              <span className="hidden sm:inline">Новая запись</span>
            </Button>
            <Button
              variant="ghost"
              onClick={() => (settingsOpen ? setSettingsOpen(false) : openSettings())}
              ariaLabel="Настройки"
              ariaExpanded={settingsOpen}
            >
              <SettingsIcon aria-hidden className="h-4 w-4" />
            </Button>
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
        <aside className="rail no-print order-2 self-start lg:order-1">
          {/* "New" and "Settings" are app-level, so they sit in the header, which
              stays on screen at every width. The rail is only the history. */}
          <h2 className="font-mono text-[12px] font-medium uppercase tracking-[0.12em] text-stone-500">
            История
          </h2>
          {sessions.length > 0 ? (
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Поиск"
              aria-label="Поиск по истории"
              className={`${FIELD} mt-3 w-full text-sm placeholder:text-stone-500`}
            />
          ) : null}
          {sessions.length === 0 ? (
            <p className="mt-3 text-sm text-stone-500">Здесь появятся обработанные записи</p>
          ) : visibleSessions.length === 0 ? (
            <p className="mt-3 text-sm text-stone-500">Нет записей с таким названием</p>
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
                      className={`${FIELD} min-w-0 flex-1 text-sm`}
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
                            ? "bg-stone-100 text-accent-700"
                            : "text-stone-600 hover:bg-stone-50"
                        }`}
                      >
                        <span className="block truncate text-sm">{session.name}</span>
                        {/* PII count, plus whether a summary exists: the list is
                            for finding a recording fast, and "does this one have
                            the answer or only the text" is worth knowing there. */}
                        <span className="block truncate text-[12px] tabular-nums text-stone-500">
                          {/* JSX drops a newline between expressions, so the
                              separator has to be written out or the row reads
                              "выжимка5 персональных данных". */}
                          {Object.keys(session.summaries).length ? "выжимка" : "без выжимки"},{" "}
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
                        className="focus-ring relative grid h-7 w-7 shrink-0 place-items-center rounded text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-700 focus-visible:text-stone-700 before:absolute before:-inset-2 before:content-['']"
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
                            className="focus-ring rounded px-1.5 py-0.5 text-xs text-stone-600 hover:bg-stone-50"
                          >
                            Нет
                          </button>
                        </span>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(session.id)}
                          aria-label={`Удалить запись ${session.name}`}
                          title="Удалить запись"
                          className="focus-ring relative grid h-7 w-7 shrink-0 place-items-center rounded text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-700 focus-visible:text-stone-700 before:absolute before:-inset-2 before:content-['']"
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
        </aside>

        <main {...dropHandlers} className={`order-1 min-w-0 lg:order-2 ${dragging ? "rounded-lg ring-2 ring-accent-300" : ""}`}>
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
                className="focus-ring -ml-1 mb-3 inline-flex items-center gap-1.5 rounded text-sm text-stone-500 hover:text-stone-900"
              >
                <ArrowLeft aria-hidden className="h-4 w-4" />
                {settingsFrom === "document" ? "К протоколу" : "К записям"}
              </button>
              <h2 className="text-lg font-semibold tracking-tight text-stone-900">Настройки</h2>
              <p className="mt-1 text-sm text-stone-600">
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
            <div className="mb-6 border border-red-300 bg-red-50 px-4 py-3">
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
              <ProgressBar pct={progress.pct} message={progress.message} eta={eta} startedAt={runStartedAt} />
              {/* Only when a document is behind the bar. On a fresh run the
                  working panel below already names the file. */}
              {workingOn && view !== "empty" ? (
                <p className="mt-1 truncate font-mono text-[12px] text-stone-600">{workingOn}</p>
              ) : null}
            </div>
          ) : null}

          {/* Summarising has no stream of its own -- one provider call, one wait --
              so the bar is given a stage name of its own rather than reusing the
              transcription line, which would name the wrong thing. */}
          {!settingsOpen && busy === "summarising" ? (
            <div>
              <ProgressBar pct={70} message="Модель читает текст и пишет выжимку" startedAt={runStartedAt} />
              {workingOn ? <p className="mt-1 truncate font-mono text-[12px] text-stone-600">{workingOn}</p> : null}
            </div>
          ) : null}

          {!settingsOpen && error ? (
            <div className="border border-red-300 bg-red-50 px-4 py-3" role="status">
              <p className="text-sm font-medium text-red-900">Не получилось</p>
              <p className="mt-1 text-sm text-red-800">{error}</p>
            </div>
          ) : null}

          {!settingsOpen && view === "empty" && !error && busy !== "analysing" ? (
            <div className="no-print flex min-h-[380px] flex-col items-center justify-center rounded-lg border border-dashed border-stone-300 px-6 py-12 text-center">
              <Mark className="h-10 w-10" />
              <h2 className="mt-4 max-w-sm text-lg font-semibold tracking-tight text-stone-900">
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
              <p className="mx-auto mt-3 max-w-md text-sm text-stone-500">
                Или перетащите сюда. Подойдёт почти любой формат
              </p>
            </div>
          ) : null}

          {!settingsOpen && view === "empty" && busy === "analysing" ? (
            <div className="no-print flex min-h-[380px] flex-col items-center justify-center rounded-lg border border-dashed border-stone-300 px-6 py-12 text-center">
              <Mark className="h-10 w-10" />
              <h2 className="mt-4 max-w-sm text-lg font-semibold tracking-tight text-stone-900">
                Обрабатываем запись
              </h2>
              {workingOn ? (
                <p className="mt-2 max-w-sm truncate font-mono text-xs text-stone-500">{workingOn}</p>
              ) : null}
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
              mode={shownMode}
              onMode={setShownMode}
              onPreset={setPreset}
              onResummarise={() => runSummary(current)}
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
