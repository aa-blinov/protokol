<script lang="ts">
  import ChevronDown from "lucide-svelte/icons/chevron-down";
  import ChevronUp from "lucide-svelte/icons/chevron-up";
  import { onMount } from "svelte";
  import { readable, type Readable } from "svelte/store";
  import {
    Button,
    EmptyState,
    IconButton,
    SearchField,
    Notice,
    Progress,
    SidebarItem,
    TextField,
    Toaster,
    toast,
  } from "@monos/ui";
  import {
    ArrowLeft,
    Moon,
    Pencil,
    Plus,
    Settings as SettingsIcon,
    Sun,
    Trash2,
  } from "lucide-svelte";
  import {
    analyseAudio,
    getSessions,
    getSettings,
    saveSessions,
    summarize,
    type AnalysisProgress,
    type EstimateResult,
    type Session,
    type SettingsState,
  } from "./api";
  import { formatCount, humanDuration, pluralRu, useEstimate } from "./lib/format";
  import { chipClass, findHits } from "./lib/highlight";
  import {
    PRODUCT_NAME,
    buildReport,
    downloadText,
    humanSeconds,
    maskedPieces,
    transcriptText,
  } from "./lib/shell";
  import ComposeGate from "./components/ComposeGate.svelte";
  import CopyButton from "./components/CopyButton.svelte";
  import Markdown from "./components/Markdown.svelte";
  import Review from "./components/Review.svelte";
  import Section from "./components/Section.svelte";
  import Settings from "./components/Settings.svelte";
  import SummaryControls from "./components/SummaryControls.svelte";
  import Transcript from "./components/Transcript.svelte";

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
  /** Откуда открыли настройки: из пустого экрана, из истории или из протокола. */
  type SettingsFrom = "empty" | "document";

  let sessions: Session[] = [];
  let current: Session | null = null;
  let view: View = "empty";
  let busy: Busy = "none";
  let progress: AnalysisProgress | null = null;
  let error: string | null = null;
  /** The drop ring, shown while a file is over the page. */
  let dragging = false;
  let settings: SettingsState | null = null;
  let preset = "";
  /** The mode whose summary is on screen for the open recording; null means the default choice. */
  let shownMode: string | null = null;
  let settingsOpen = false;
  let settingsFrom: SettingsFrom = "empty";
  /** Seconds each stage took last time, keyed by stage name. The progress line
   *  turns them into "осталось примерно N с" -- honest, because the estimate
   *  comes from this machine's own earlier runs rather than a guess. */
  let stageTimings: Record<string, number> = {};
  let eta: number | null = null;
  let elapsed = 0;
  /** Row awaiting a delete confirmation. Removing a transcript is destructive
   *  and cannot be undone, so it takes a second, deliberate click. */
  let confirmDeleteId: string | null = null;
  /** Name of the file currently being worked on, so the progress bar can say
   *  which recording it belongs to; without it the bar sits above a finished
   *  document and the two get confused. */
  let workingOn: string | null = null;
  /** The search over the history rail. */
  let historyQuery = "";
  /** The search over the transcript of the open document. */
  let docQuery = "";
  let docCursor = 0;
  let editingId: string | null = null;
  let draft = "";
  /** The saved choice, read before the first paint: the dark half is the
   *  default and the saved value wins only when it says "light". */
  let theme: "light" | "dark" = savedTheme();
  /** Which sections the reader has folded away. The masked text starts folded:
   *  it is the part a reader verifies rather than reads. */
  let folded: Record<string, boolean> = { masked: true };
  /** Whether the compose form under the summary is open. */
  let redoOpen = false;

  let fileInput: HTMLInputElement | null = null;
  let headerEl: HTMLElement | null = null;
  let listEl: HTMLUListElement | null = null;
  let dragDepth = 0;
  let hydrated = false;
  let scrollKey = "";

  $: showDocument = view === "document" && current !== null;
  $: showReview = view === "review" && current !== null;
  /** Modes that already have one, so moving between them costs no call. */
  $: made = current ? Object.keys(current.summaries) : [];
  /** The mode on screen: the one the reader picked, else the settings' mode if it has a summary,
   *  else the latest one made. Choosing a mode in the compose form never changes it. */
  $: shown = current
    ? shownMode && made.includes(shownMode)
      ? shownMode
      : made.includes(preset)
        ? preset
        : (made[made.length - 1] ?? preset)
    : "";
  /** The summary of the mode on screen. It disappears only when that mode is left unmade. */
  $: summary = current ? current.summaries[shown] ?? null : null;
  $: speakers = current
    ? new Set(current.analysis.segments.map((segment) => segment.speaker)).size
    : 0;
  $: entityCount = current ? Object.keys(current.analysis.entity_map).length : 0;
  $: hits = current ? findHits(current.analysis.transcript, docQuery) : [];
  $: visibleSessions = historyQuery
    ? sessions.filter((session) =>
        session.name.toLowerCase().includes(historyQuery.trim().toLowerCase()),
      )
    : sessions;
  /** Recordings from before the pipeline was split have no cached analysis, so
   *  a second summary would have nothing to run on. Saying so beats offering a
   *  button that answers "анализ не найден". */
  $: canResummarise = current
    ? current.analysis.masked_text.trim() !== "" && Boolean(settings?.has_key)
    : false;
  $: allowExport = settings?.policy?.allow_export !== false;
  $: anyFolded = Object.values(folded).some(Boolean);
  $: estimate = showDocument && settings
    ? useEstimate(current?.analysis.masked_text.length ?? 0, settings.model)
    : readable<EstimateResult | null>(null);

  $: barMessage =
    busy === "summarising" ? "Модель читает текст и пишет выжимку" : (progress?.message ?? "");
  $: barPct = busy === "summarising" ? 70 : (progress?.pct ?? 0);
  $: barEta = busy === "summarising" ? null : eta;

  // The history is written back on every change, but only once it was read:
  // saving an empty list before the load finished would wipe the history.
  $: if (hydrated && sessions.length) void saveSessions(sessions).catch(() => undefined);

  // Reset the cursor on a new query and on a different recording: the second
  // leaves the cursor pointing past the end of a shorter list.
  $: resetCursor(docQuery, current?.analysis.transcript);

  // Смена экрана должна возвращать к началу. Иначе: читаете длинный протокол,
  // жмёте «Новая запись», выбираете файл — контент наверху меняется, а
  // прокрутка остаётся там, где была, и кажется, что ничего не произошло.
  $: {
    const key = `${view}:${busy === "analysing"}`;
    if (key !== scrollKey) {
      scrollKey = key;
      if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "auto" });
    }
  }

  // Открытая запись всегда должна быть в поле зрения: переход к ней может
  // прийти не из списка, и прокручивать его руками не должен никто.
  $: scrollActiveIntoView(current, visibleSessions);

  function resetCursor(_query: string, _transcript: string | undefined) {
    docCursor = 0;
  }

  function scrollActiveIntoView(_current: Session | null, _visible: Session[]) {
    if (!current) return;
    listEl
      ?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }

  /** The theme belongs to the shell: children never touch it.
   *
   *  The dark half is the default; the saved choice wins only when it says
   *  "light", so a stale or unreadable value leaves the app as it was built. */
  function savedTheme(): "light" | "dark" {
    try {
      return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  }

  function applyTheme(mode: "light" | "dark") {
    theme = mode;
    const root = document.documentElement;
    root.setAttribute("data-theme", "gruvbox");
    root.setAttribute("data-mode", mode);
    // The class is kept for the browser check that still asks for the old
    // mechanism; the theme itself is the attribute above.
    root.classList.toggle("dark", mode === "dark");
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch {
      /* the choice is a convenience, not a requirement */
    }
  }

  function openPicker() {
    fileInput?.click();
  }

  function onFilePicked(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (file && busy === "none") void analyse(file);
  }

  /** Every failure goes through here. The in-flow banner stays as the record;
   *  the toast is what someone scrolled to the bottom of a document can see. */
  function notice(tone: "good" | "bad", text: string) {
    if (tone === "good") {
      toast({ title: text, tone: "success" });
      return;
    }
    // Errors stay until dismissed: a failure that quietly disappears is the
    // same failure the person could not find in the first place.
    toast({ title: text, tone: "danger", duration: 0 });
  }

  function fail(text: string) {
    error = text;
    notice("bad", text);
  }

  /** Drop a file: transcribe, mask, then stop and show what would be sent. */
  async function analyse(file: File) {
    const previousView = view;
    error = null;
    workingOn = file.name;
    busy = "analysing";
    // Возврат к экрану разбора нужен сразу. Оба его состояния — идущий разбор
    // и пустой экран — отрисованы только при view === "empty". Когда новый файл
    // выбирают из документа, view оставался "document" весь разбор, и человек
    // видел старый протокол до самой секунды появления выжимки.
    view = "empty";
    progress = { stage: "transcribe", pct: 0, message: "Загрузка файла" };
    try {
      const result = await analyseAudio(file, (event) => {
        progress = event;
        const known = stageTimings[event.stage];
        eta = known !== undefined ? known * (1 - event.pct / 100) : null;
      });
      const session: Session = {
        id: crypto.randomUUID(),
        name: file.name,
        createdAt: new Date().toISOString(),
        analysis: result,
        summaries: {},
      };
      sessions = [session, ...sessions].slice(0, 50);
      current = session;
      // Remembered only on success: a failed run has no timings to learn from.
      if (result.timings) stageTimings = { ...stageTimings, ...result.timings };
      view = "review";
    } catch (caught) {
      // The failed file is not the session on screen — drop that stale result,
      // otherwise the error reads as belonging to the document below it.
      fail(caught instanceof Error ? caught.message : String(caught));
      // Неудавшийся файл к открытому документу отношения не имеет: возвращаемся
      // туда, откуда начали, иначе человек теряет место без причины.
      view = previousView;
    } finally {
      busy = "none";
      progress = null;
      workingOn = null;
      eta = null;
    }
  }

  /** Ask for the summary over the analysis already in hand. */
  async function runSummary(session: Session): Promise<boolean> {
    if (!settings) return false;
    error = null;
    busy = "summarising";
    workingOn = session.name;
    try {
      const result = await summarize(
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
      sessions = sessions.map((item) => (item.id === session.id ? filed : item));
      // The screen moves to the summary just made; the others stay under their own chips.
      shownMode = result.preset ?? preset;
      current = current && current.id === session.id ? filed : current;
      // A summary means there is something to read, so land on the document.
      view = "document";
      // Tells the caller the summary is made, so its compose form can close.
      return true;
    } catch (caught) {
      fail(caught instanceof Error ? caught.message : String(caught));
      return false;
    } finally {
      busy = "none";
      workingOn = null;
    }
  }

  function openSettings() {
    settingsFrom = view === "document" && current ? "document" : "empty";
    settingsOpen = true;
  }

  function closeSettings() {
    settingsOpen = false;
  }

  function handleSaved(saved: SettingsState) {
    settings = saved;
    // Saving from the dialog is an explicit choice of focus, so it becomes the
    // default everywhere -- including on a review screen that is open with a
    // different one selected. The review screen's own picker stays a per-run
    // override.
    preset = saved.preset;
  }

  function openSession(session: Session) {
    current = session;
    view = "document";
    error = null;
  }

  function removeSession(id: string) {
    sessions = sessions.filter((session) => session.id !== id);
    current = current && current.id === id ? null : current;
  }

  function renameSession(id: string, name: string) {
    const trimmed = name.trim();
    sessions = sessions.map((session) =>
      session.id === id ? { ...session, name: trimmed || session.name } : session,
    );
    if (current && current.id === id) {
      current = { ...current, name: trimmed || current.name };
    }
    editingId = null;
  }

  /** The mode row of the document: a made mode shows its own summary, an
   *  unmade one opens the compose form for that mode. The form does not change
   *  what is on screen until its summary exists. */
  function pickMode(key: string) {
    if (made.includes(key)) {
      shownMode = key;
      return;
    }
    preset = key;
    redoOpen = true;
  }

  /** The kit's SearchField dispatches the native event, so the value is read
   *  from the detail and, failing that, from the input itself. */
  function onSearchInput(event: CustomEvent<{ value: string }> & { target: HTMLInputElement }) {
    docQuery = event.detail?.value ?? event.target.value;
  }

  function stepCursor(direction: number) {
    if (!hits.length) return;
    docCursor = (docCursor + direction + hits.length) % hits.length;
  }

  function toggleFold(key: string) {
    folded = { ...folded, [key]: !folded[key] };
  }

  function toggleAll() {
    folded = anyFolded ? {} : { summary: true, transcript: true, masked: true };
  }

  function onDocumentKeydown(event: KeyboardEvent) {
    // Ворота живут внутри документа, поэтому Escape ловится здесь: из
    // родителя до них не дотянуться.
    if (event.key === "Escape" && redoOpen) {
      event.stopPropagation();
      redoOpen = false;
    }
  }

  function onListKeydown(event: KeyboardEvent) {
    const items = Array.from(listEl?.querySelectorAll<HTMLElement>("[data-item]") ?? []);
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
      editingId = items[at].dataset.id ?? null;
      draft = items[at].dataset.name ?? "";
    } else if ((event.key === "Delete" || event.key === "Backspace") && at > -1) {
      event.preventDefault();
      confirmDeleteId = items[at].dataset.id ?? null;
    }
  }

  function onWindowKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      if (settingsOpen) settingsOpen = false;
      else if (confirmDeleteId) confirmDeleteId = null;
      else if (historyQuery) historyQuery = "";
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "o") {
      event.preventDefault();
      if (busy === "none") openPicker();
      return;
    }
    // Enter walks the matches from anywhere on the page, not only while the
    // field has focus: the point of the search is to stop looking at the input
    // and read.
    if (event.key === "Enter" && showDocument && hits.length) {
      if (event.target instanceof HTMLInputElement) return;
      if (event.target instanceof HTMLTextAreaElement) return;
      event.preventDefault();
      stepCursor(event.shiftKey ? -1 : 1);
    }
  }

  function onDragEnter(event: DragEvent) {
    event.preventDefault();
    dragDepth += 1;
    dragging = true;
  }

  function onDragOver(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  }

  function onDragLeave(event: DragEvent) {
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dragging = false;
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragDepth = 0;
    dragging = false;
    // Dropping a second file mid-run started a parallel transcription whose
    // result then replaced the first one's session. Better to ignore it: the
    // run in progress already owns the screen.
    if (busy !== "none") return;
    const file = event.dataTransfer?.files?.[0];
    if (file) void analyse(file);
  }

  function downloadReport() {
    if (!current) return;
    const labels = Object.fromEntries(
      (settings?.presets ?? []).map((item) => [item.key, item.label]),
    );
    downloadText(
      `${current.name.replace(/\.[^.]+$/, "")} (расшифровка).txt`,
      buildReport(current, labels),
    );
  }

  async function composeRun() {
    if (!current) return;
    // The compose form closes only when the summary really was made: a failed
    // call leaves it open, with the error next to the button that failed.
    if (await runSummary(current)) redoOpen = false;
  }

  function sendSummary() {
    if (current) void runSummary(current);
  }

  onMount(() => {
    // The bar under the header sticks at the header's bottom edge. The edge is
    // measured, not assumed: the header follows its buttons and title, and it
    // has already moved from 77 px to 69 px.
    const measure = () => {
      if (!headerEl) return;
      document.documentElement.style.setProperty(
        "--header-h",
        `${headerEl.getBoundingClientRect().height}px`,
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (headerEl) observer.observe(headerEl);

    window.addEventListener("keydown", onWindowKeydown);

    applyTheme(theme);

    void getSessions()
      .then((loaded) => {
        sessions = loaded;
      })
      .catch(() => {
        sessions = [];
      })
      .finally(() => {
        hydrated = true;
      });

    // The model and the focus come from the saved settings, not from constants:
    // the dialog is the only place they are chosen, so starting with hardcoded
    // values would silently override whatever the user picked.
    void getSettings()
      .then((loaded) => {
        settings = loaded;
        preset = loaded.preset;
      })
      .catch(() => {
        settings = null;
      });

    return () => {
      observer.disconnect();
      window.removeEventListener("keydown", onWindowKeydown);
    };
  });
</script>

<div class="min-h-full">
  <header
    bind:this={headerEl}
    class="no-print sticky top-0 z-10 border-b border-line bg-surface"
  >
    <div class="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
      <!-- The product mark: a page with one line redacted. Drawn in the current
           ink rather than in a colour: the kit has no filled brand block, and a
           sheet of paper is a better mark for a protocol than a coloured tile. -->
      <svg
        viewBox="0 0 32 32"
        class="h-7 w-7 shrink-0 text-ink"
        role="img"
        aria-label={PRODUCT_NAME}
        fill="none"
        stroke="currentColor"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <rect x="7" y="4" width="18" height="24" rx="5" stroke-width="2" />
        <path d="M11 11h10M11 16h10M11 21h6" stroke-width="2" />
      </svg>
      <div class="min-w-0">
        <h1 class="text-lg font-bold tracking-tight text-ink">{PRODUCT_NAME}</h1>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button
          variant="quiet"
          on:click={openPicker}
          disabled={busy !== "none"}
          aria-label="Новая запись"
        >
          <svelte:fragment slot="icon">
            <Plus size={16} strokeWidth={1.7} aria-hidden="true" />
          </svelte:fragment>
          <span class="hidden sm:inline">Новая запись</span>
        </Button>
        <IconButton
          label="Настройки"
          variant="ghost"
          on:click={() => (settingsOpen ? closeSettings() : openSettings())}
          aria-expanded={settingsOpen}
        >
          <SettingsIcon size={16} strokeWidth={1.7} aria-hidden="true" />
        </IconButton>
        <IconButton
          label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          variant="ghost"
          on:click={() => applyTheme(theme === "dark" ? "light" : "dark")}
        >
          {#if theme === "dark"}
            <Sun size={16} strokeWidth={1.7} aria-hidden="true" />
          {:else}
            <Moon size={16} strokeWidth={1.7} aria-hidden="true" />
          {/if}
        </IconButton>
      </div>
    </div>
  </header>

  <div
    class="mx-auto grid max-w-5xl grid-cols-1 gap-x-10 gap-y-8 px-6 py-8 lg:grid-cols-[200px_1fr] print:grid-cols-1"
  >
    <aside class="rail no-print order-2 self-start lg:order-1">
      <!-- "New" and "Settings" are app-level, so they sit in the header, which
           stays on screen at every width. The rail is only the history. -->
      <h2 class="font-ui text-[12px] font-medium uppercase tracking-[0.12em] text-ink-muted">
        История
      </h2>
      {#if sessions.length > 0}
        <div class="mt-3">
          <TextField
            bind:value={historyQuery}
            variant="boxed"
            size="sm"
            placeholder="Поиск"
            aria-label="Поиск по истории"
          />
        </div>
      {/if}
      {#if sessions.length === 0}
        <p class="mt-3 text-sm text-ink-muted">Здесь появятся обработанные записи</p>
      {:else if visibleSessions.length === 0}
        <p class="mt-3 text-sm text-ink-muted">Нет записей с таким названием</p>
      {:else}
        <!-- The list is a keyboard surface of its own: the arrows move between
             the rows, F2 renames and Delete asks before removing. The handler
             lives on the list because the focus is on a button inside a row. -->
        <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
        <ul
          bind:this={listEl}
          aria-label="Обработанные записи"
          class="mt-2 space-y-0.5"
          on:keydown={onListKeydown}
        >
          {#each visibleSessions as session (session.id)}
            <li
              data-item
              data-id={session.id}
              data-name={session.name}
              data-active={current?.id === session.id && !showReview ? "true" : "false"}
              class="group flex items-start gap-1"
            >
              {#if editingId === session.id}
                <!-- The field takes the focus as it appears: renaming without
                     the cursor in the name is renaming nothing. -->
                <!-- svelte-ignore a11y-autofocus -->
                <input
                  autofocus
                  bind:value={draft}
                  on:blur={() => renameSession(session.id, draft)}
                  on:keydown={(event) => {
                    if (event.key === "Enter") event.currentTarget.blur();
                    if (event.key === "Escape") editingId = null;
                  }}
                  aria-label="Новое имя сессии"
                  class="min-w-0 flex-1 rounded-ui border border-line bg-surface px-3 py-2 text-sm leading-5 text-ink outline-none transition-colors duration-fast focus:border-ink-soft"
                />
              {:else}
                <SidebarItem
                  active={current?.id === session.id && !showReview}
                  on:click={() => openSession(session)}
                >
                  <span class="block truncate text-sm">{session.name}</span>
                  <!-- PII count, plus whether a summary exists: the list is
                       for finding a recording fast, and "does this one have
                       the answer or only the text" is worth knowing there. -->
                  <span class="block truncate text-[12px] tabular-nums text-ink-muted">
                    {Object.keys(session.summaries).length ? "выжимка" : "без выжимки"}{" "}
                    {session.analysis.entities.length}{" "}
                    {pluralRu(
                      session.analysis.entities.length,
                      "персональных данных",
                      "персональных данных",
                      "персональных данных",
                    )}
                  </span>
                </SidebarItem>
                <IconButton
                  label={`Переименовать запись ${session.name}`}
                  tooltipText="Переименовать"
                  variant="ghost"
                  size="sm"
                  on:click={() => {
                    editingId = session.id;
                    draft = session.name;
                  }}
                >
                  <Pencil size={16} strokeWidth={1.7} aria-hidden="true" />
                </IconButton>
                {#if confirmDeleteId === session.id}
                  <span class="mt-1 flex items-center gap-1">
                    <Button
                      variant="danger"
                      size="sm"
                      on:click={() => {
                        removeSession(session.id);
                        confirmDeleteId = null;
                      }}
                    >
                      Удалить
                    </Button>
                    <Button
                      variant="quiet"
                      size="sm"
                      on:click={() => (confirmDeleteId = null)}
                    >
                      Нет
                    </Button>
                  </span>
                {:else}
                  <IconButton
                    label={`Удалить запись ${session.name}`}
                    tooltipText="Удалить запись"
                    variant="ghost"
                    size="sm"
                    on:click={() => (confirmDeleteId = session.id)}
                  >
                    <Trash2 size={16} strokeWidth={1.7} aria-hidden="true" />
                  </IconButton>
                {/if}
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </aside>

    <main
      class="order-1 min-w-0 lg:order-2 {dragging ? 'rounded-ui ring-2 ring-accent' : ''}"
      on:dragenter={onDragEnter}
      on:dragover={onDragOver}
      on:dragleave={onDragLeave}
      on:drop={onDrop}
    >
      <input
        bind:this={fileInput}
        type="file"
        accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.mp4"
        class="hidden"
        on:change={onFilePicked}
      />

      {#if settingsOpen}
        <div class="max-w-2xl">
          <!-- Назад — слева и над заголовком, как в браузере, почте и любом
               мастере настроек. Кнопка в правом углу читалась как ещё одно
               действие рядом с формой, а навигация должна читаться как
               навигация: мелко, приглушённо, над тем, куда возвращают. -->
          <Button
            variant="quiet"
            size="sm"
            class="-ml-1 mb-3"
            on:click={closeSettings}
            aria-label={settingsFrom === "document" ? "Вернуться к протоколу" : "Вернуться к записям"}
          >
            <svelte:fragment slot="icon">
              <ArrowLeft size={16} strokeWidth={1.7} aria-hidden="true" />
            </svelte:fragment>
            {settingsFrom === "document" ? "К протоколу" : "К записям"}
          </Button>
          <h2 class="text-lg font-bold tracking-tight text-ink">Настройки</h2>
          <p class="mt-1 text-sm text-ink-soft">
            Здесь выбирается сервис, который составит выжимку, и ключ к нему. Всё хранится на этом
            компьютере.
          </p>
          <Settings on:saved={(event) => handleSaved(event.detail)} />
        </div>
      {/if}

      {#if !settingsOpen && settings && !settings.has_key && view === "empty"}
        <div class="mb-6">
          <Notice tone="warning" title="Не задан ключ">
            Запись всё равно расшифруется и личные данные будут скрыты, но ответа модели не будет.
            Откройте
            <Button variant="text" size="sm" on:click={openSettings}>«Настройки»</Button>
            в левой панели и вставьте ключ.
          </Notice>
        </div>
      {/if}

      {#if !settingsOpen && (progress || busy === "summarising")}
        <div>
          <div class="space-y-2">
            <div class="flex items-baseline justify-between gap-3 text-xs text-ink-soft">
              <!-- Only the stage message is a live region. Announcing the
                   percentage on every tick would talk over the screen reader
                   for a minute. -->
              <span role="status">{barMessage}</span>
              <span class="flex shrink-0 items-baseline gap-2">
                <!-- One time figure, and only one we can stand behind. A previous
                     measurement gives a remainder; without one, elapsed time is the
                     honest answer -- showing nothing for the first minute reads as a
                     hang. -->
                {#if barEta !== null && barEta > 0}
                  <span class="text-ink-muted">осталось примерно {humanSeconds(barEta)}</span>
                {:else if elapsed}
                  <span class="text-ink-muted">прошло {humanSeconds(elapsed)}</span>
                {/if}
                <span class="font-ui tabular-nums text-ink-muted">{barPct}%</span>
              </span>
            </div>
            <Progress value={barPct} label={barMessage} />
          </div>
          <!-- Only when a document is behind the bar. On a fresh run the
               working panel below already names the file. -->
          {#if workingOn && (view !== "empty" || busy === "summarising")}
            <p class="mt-1 truncate font-ui text-[12px] text-ink-soft">{workingOn}</p>
          {/if}
        </div>
      {/if}

      {#if !settingsOpen && error}
        <Notice tone="danger" title="Не получилось">{error}</Notice>
      {/if}

      {#if !settingsOpen && view === "empty" && !error && busy !== "analysing"}
        <div class="no-print rounded-ui border border-line">
          <EmptyState
            title="Загрузите запись встречи"
            description="Или перетащите сюда. Подойдёт почти любой формат"
          >
            <svelte:fragment slot="icon">
              <svg
                viewBox="0 0 32 32"
                class="h-10 w-10 text-ink-muted"
                fill="none"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <rect x="7" y="4" width="18" height="24" rx="5" stroke-width="2" />
                <path d="M11 11h10M11 16h10M11 21h6" stroke-width="2" />
              </svg>
            </svelte:fragment>
            <svelte:fragment slot="actions">
              <Button variant="primary" size="lg" on:click={openPicker} disabled={busy !== "none"}>
                Выбрать аудиофайл
              </Button>
            </svelte:fragment>
          </EmptyState>
        </div>
      {/if}

      {#if !settingsOpen && view === "empty" && busy === "analysing"}
        <div class="no-print rounded-ui border border-line">
          <EmptyState title="Обрабатываем запись" description={workingOn ?? ""}>
            <svelte:fragment slot="icon">
              <svg
                viewBox="0 0 32 32"
                class="h-10 w-10 text-ink-muted"
                fill="none"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <rect x="7" y="4" width="18" height="24" rx="5" stroke-width="2" />
                <path d="M11 11h10M11 16h10M11 21h6" stroke-width="2" />
              </svg>
            </svelte:fragment>
          </EmptyState>
        </div>
      {/if}

      {#if !settingsOpen && showReview && settings && current}
        <Review
          name={current.name}
          analysis={current.analysis}
          settings={settings}
          preset={preset || settings.preset}
          busy={busy === "summarising"}
          on:preset={(event) => (preset = event.detail)}
          on:send={sendSummary}
          on:skip={() => (view = "document")}
          on:openSettings={openSettings}
        />
      {/if}

      {#if !settingsOpen && showDocument && settings && current}
        <!-- The document is a keyboard surface: Escape closes the compose form
             under the summary, and the handler has to be inside the document,
             because from the parent the gate is out of reach. -->
        <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
        <article on:keydown={onDocumentKeydown}>
          <header>
            <h2 class="break-words text-2xl font-bold tracking-tight text-ink">{current.name}</h2>
            <!-- Metadata is separated by space, not by dots: a row of · reads as
                 decoration. The model id is left out entirely — it belongs to the
                 settings screen, and "deepseek/deepseek-v4.1-flash" means nothing to
                 whoever opens the document. -->
            <p class="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-ink-muted">
              <span class={summary ? "text-accent-text" : ""}>
                {made.length
                  ? summary
                    ? "С выжимкой"
                    : // There are summaries, just not for the mode on screen. Saying
                      // «только расшифровка» here would be a lie the reader has no
                      // way to disprove without opening every other mode.
                      "Выжимка в другом режиме"
                  : "Только расшифровка"}
              </span>
              <time datetime={current.createdAt} class="tabular-nums">
                {new Date(current.createdAt).toLocaleString("ru-RU", {
                  dateStyle: "short",
                  timeStyle: "short",
                })}
              </time>
              <span class="tabular-nums">{humanDuration(current.analysis.duration_sec)}</span>
              <span>
                {current.analysis.entities.length}{" "}
                {pluralRu(
                  current.analysis.entities.length,
                  "персональных данных",
                  "персональных данных",
                  "персональных данных",
                )}
              </span>
              {#if speakers > 1}
                <span>
                  {speakers} {pluralRu(speakers, "спикер", "спикера", "спикеров")}
                </span>
              {/if}
            </p>
          </header>

          <!-- Outside the document header on purpose: a sticky element travels only
               inside its own parent, and the header is 119 px tall — the bar would
               have stuck for 119 px and then scrolled away exactly as before. -->
          <div
            style="top: var(--header-h, 69px)"
            class="no-print sticky z-[5] flex flex-wrap items-center gap-4 border-b border-line bg-canvas py-3"
          >
            <!-- The search sits in the sticky bar, not in the transcript
                 section: inside the section it folded away with the section,
                 and searching meant unfolding a dozen screens of text first. -->
            <div class="min-w-[13rem] flex-1">
              <SearchField
                value={docQuery}
                label="Поиск по расшифровке"
                placeholder="Поиск по расшифровке"
                clearLabel="Очистить поиск"
                on:input={onSearchInput}
                on:clear={() => (docQuery = "")}
              />
            </div>
            {#if docQuery}
              <div class="flex items-center gap-1">
                <span class="tabular-nums text-xs text-ink-muted">
                  {hits.length ? `${docCursor + 1} из ${hits.length}` : "не найдено"}
                </span>
                <IconButton
                  label="Предыдущее совпадение"
                  variant="outline"
                  size="md"
                  disabled={!hits.length}
                  on:click={() => stepCursor(-1)}
                >
                  <ChevronUp size={16} strokeWidth={1.7} />
                </IconButton>
                <IconButton
                  label="Следующее совпадение"
                  variant="outline"
                  size="md"
                  disabled={!hits.length}
                  on:click={() => stepCursor(1)}
                >
                  <ChevronDown size={16} strokeWidth={1.7} />
                </IconButton>
              </div>
            {/if}
            {#if allowExport}
              <Button variant="quiet" on:click={downloadReport}>Скачать .txt</Button>
              <Button variant="quiet" on:click={() => window.print()}>Печать / PDF</Button>
            {/if}
            <Button variant="quiet" on:click={toggleAll}>
              {anyFolded ? "Развернуть всё" : "Свернуть всё"}
            </Button>
          </div>

          <!-- Size, not how long the model took: recordings summarised before the
               pipeline was split carry no timings, and "0 с на подготовку" reads as
               a measured zero rather than a number nobody wrote down. -->
          <Section
            label="Выжимка"
            collapsed={Boolean(folded.summary)}
            collapsedNote={summary
              ? `${formatCount(summary.reply_unmasked.length)} знаков`
              : made.length
                ? `составлена в другом режиме, вариантов: ${made.length}`
                : "не составлялась"}
            onToggle={() => toggleFold("summary")}
          >
            <svelte:fragment slot="meta">
              {#if summary && allowExport}
                <CopyButton text={summary.reply_unmasked} />
              {/if}
            </svelte:fragment>
            <SummaryControls
              settings={settings}
              summaries={current.summaries}
              summary={summary}
              mode={shown}
              busy={busy === "summarising"}
              open={redoOpen}
              on:preset={(event) => pickMode(event.detail)}
              on:run={() => (redoOpen = !redoOpen)}
            />
            {#if summary}
              {#if summary.warnings?.length}
                <ul class="mb-4 space-y-1 border border-line bg-surface-2 px-3 py-2 text-sm text-ink-soft">
                  {#each summary.warnings as warning (warning)}
                    <li>{warning}</li>
                  {/each}
                </ul>
              {/if}
              <Markdown text={summary.reply_unmasked} />
              {#if redoOpen}
                <div class="no-print mt-4">
                  <ComposeGate
                    settings={settings}
                    preset={preset}
                    estimate={$estimate}
                    busy={busy}
                    canRun={canResummarise}
                    runLabel="Составить выжимку"
                    closeLabel="Оставить как есть"
                    on:preset={(event) => (preset = event.detail)}
                    on:run={() => void composeRun()}
                    on:close={() => (redoOpen = false)}
                    on:openSettings={openSettings}
                  />
                </div>
              {/if}
              <details class="no-print mt-4">
                <summary class="cursor-pointer text-xs text-ink-muted hover:text-ink">
                  Что модель увидела вместо имён
                </summary>
                <div
                  class="mt-3 max-w-[68ch] rounded-ui border border-line bg-surface-2 p-3 text-[13px] leading-6 text-ink-soft"
                >
                  <p class="whitespace-pre-wrap leading-7 text-ink">
                    {#each maskedPieces(summary.reply) as piece}
                      {#if piece.token}
                        <mark
                          class={chipClass(piece.type ?? "")}
                          title="{piece.token} → {current.analysis.entity_map[piece.token] ?? ''}"
                        >{piece.token}</mark
                        >
                      {:else}{piece.text}{/if}
                    {/each}
                  </p>
                </div>
              </details>
            {:else if redoOpen}
              <ComposeGate
                settings={settings}
                preset={preset}
                estimate={$estimate}
                busy={busy}
                canRun={canResummarise}
                runLabel="Составить выжимку"
                closeLabel="Оставить только расшифровку"
                on:preset={(event) => (preset = event.detail)}
                on:run={() => void composeRun()}
                on:close={() => (redoOpen = false)}
                on:openSettings={openSettings}
              />
            {:else}
              <div class="max-w-xl">
                <p class="text-sm text-ink-soft">
                  Вы остановились на расшифровке. Выжимку не отправляли, деньги не потрачены.
                </p>
                <div class="no-print mt-4 flex flex-wrap items-center gap-4">
                  <Button
                    variant="primary"
                    on:click={() => (redoOpen = true)}
                    disabled={busy === "summarising"}
                  >
                    Составить выжимку
                  </Button>
                  {#if !canResummarise}
                    <p class="text-xs text-ink-muted">
                      Готовой расшифровки от прошлого раза не осталось, поэтому составить выжимку
                      можно будет только после повторной загрузки файла.
                    </p>
                  {/if}
                </div>
              </div>
            {/if}
          </Section>

          <Section
            label="Расшифровка"
            collapsed={Boolean(folded.transcript) && docQuery.trim() === ""}
            collapsedNote="{formatCount(transcriptText(current.analysis).length)} знаков, {speakers >
              1
                ? `${speakers} спикеров`
                : 'один голос'}"
            onToggle={() => toggleFold("transcript")}
          >
            <svelte:fragment slot="meta">
              {#if allowExport}
                <CopyButton text={transcriptText(current.analysis)} />
              {/if}
            </svelte:fragment>
            <Transcript
              analysis={current.analysis}
              query={docQuery}
              hits={hits}
              cursor={docCursor}
              on:query={(event) => (docQuery = event.detail)}
              on:step={(event) => stepCursor(event.detail)}
            />
          </Section>

          <Section
            label="Что уходит в модель"
            collapsed={Boolean(folded.masked)}
            collapsedNote="{formatCount(current.analysis.masked_text.length)} знаков, {entityCount} {pluralRu(
              entityCount,
              'подстановка',
              'подстановки',
              'подстановок',
            )}"
            onToggle={() => toggleFold("masked")}
          >
            <!-- One level of folding, not two. The section already collapses; a
                 separate "показать целиком" inside it meant three states for what is
                 really one decision. -->
            <div class="max-h-[30rem] max-w-[68ch] overflow-y-auto text-[15px] leading-7 text-ink">
              <p class="whitespace-pre-wrap leading-7 text-ink">
                {#each maskedPieces(current.analysis.masked_text) as piece}
                  {#if piece.token}
                    <mark
                      class={chipClass(piece.type ?? "")}
                      title="{piece.token} → {current.analysis.entity_map[piece.token] ?? ''}"
                    >{piece.token}</mark
                    >
                  {:else}{piece.text}{/if}
                {/each}
              </p>
            </div>

            {#if entityCount > 0}
              <details class="no-print mt-4">
                <summary class="cursor-pointer text-xs text-ink-muted hover:text-ink">
                  Таблица подстановок
                </summary>
                <ul class="mt-3 grid gap-1.5 sm:grid-cols-2">
                  {#each Object.entries(current.analysis.entity_map) as [token, value] (token)}
                    <li class="flex items-baseline gap-2 text-xs">
                      <span class={chipClass(token.replace(/_\d+$/, ""))}>{token}</span>
                      <span class="font-ui text-ink-soft">{value}</span>
                    </li>
                  {/each}
                </ul>
              </details>
            {/if}
          </Section>
        </article>
      {/if}
    </main>
  </div>

  <Toaster position="bottom-center" dismissLabel="Закрыть" />
</div>
