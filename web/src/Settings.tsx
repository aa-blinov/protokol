/** Settings dialog: the OpenRouter key and the chat model.
 *
 *  The key is entered here rather than through a .env file because a desktop
 *  app has no shell to read one from, and because "paste the key and check it"
 *  is the whole flow a non-technical user needs. The backend keeps the key in
 *  the same settings file it already read on start, so nothing about the launch
 *  path changes.
 *
 *  The model picker is a searchable combobox over the live OpenRouter
 *  catalogue: 458 models is too many for a plain <select>, and the id people
 *  need is rarely the one that sorts first. */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getModels,
  getSettings,
  saveSettings,
  verifyKey,
  type ModelInfo,
  type SettingsState,
} from "./api";
import { Button, Section } from "./ui";
import { PresetPicker } from "./SummaryControls";
import { Eye, EyeOff, Search } from "lucide-react";

function formatPrice(value: number | null): string {
  if (value === null) return "нет";
  if (value === 0) return "бесплатно";
  return `$${value.toFixed(2)}/Млн`;
}

function formatContext(value: number | null): string {
  if (!value) return "";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(0)}M`;
  return `${Math.round(value / 1000)}K`;
}

/** Case-insensitive match over id and display name, id first so prefixes win. */
function filterModels(models: ModelInfo[], query: string): ModelInfo[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return models;
  const starts: ModelInfo[] = [];
  const contains: ModelInfo[] = [];
  for (const model of models) {
    const id = model.id.toLowerCase();
    if (id.startsWith(needle)) starts.push(model);
    else if (id.includes(needle) || model.name.toLowerCase().includes(needle)) contains.push(model);
  }
  return [...starts, ...contains].slice(0, 80);
}

function ModelPicker({
  models,
  value,
  onChange,
}: {
  models: ModelInfo[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const matches = useMemo(() => filterModels(models, query), [models, query]);
  const selected = models.find((m) => m.id === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => setActive(0), [query]);

  useEffect(() => {
    if (open) listRef.current?.querySelector<HTMLElement>("[data-active='true']")?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const pick = (id: string) => {
    onChange(id);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 rounded-md border border-slate-300 bg-white px-3 py-2 text-left text-sm hover:bg-slate-50"
      >
        <span className="min-w-0 truncate font-mono text-[13px]">
          {selected ? selected.id : <span className="text-slate-500">Модель не выбрана</span>}
        </span>
        <Search aria-hidden className="h-4 w-4 shrink-0 text-slate-500" />
      </button>

      {open ? (
        <div className="absolute z-30 mt-1 w-full min-w-0 max-w-full overflow-hidden rounded border border-slate-300 bg-white">
          <div className="border-b border-slate-200 p-2">
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setActive((i) => Math.min(i + 1, matches.length - 1));
                } else if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setActive((i) => Math.max(i - 1, 0));
                } else if (event.key === "Enter" && matches[active]) {
                  event.preventDefault();
                  pick(matches[active].id);
                } else if (event.key === "Escape") {
                  setOpen(false);
                }
              }}
              placeholder="Начните вводить название…"
              // The project ring, not a border tint: this input was the only
              // focusable thing in the app that dropped the outline, and a 1px
              // slate-400 border on slate-200 is far too quiet to navigate by.
              // focus: also fires on mouse press, which is the wrong way round.
              className="focus-ring w-full rounded border border-slate-200 px-2 py-1.5 font-mono text-[13px] focus:border-slate-400"
            />
          </div>
          <ul ref={listRef} role="listbox" className="max-h-64 overflow-y-auto py-1">
            {matches.length === 0 ? (
              <li className="px-3 py-3 text-sm text-slate-500">Ничего не найдено</li>
            ) : (
              matches.map((model, index) => (
                <li key={model.id} role="option" aria-selected={model.id === value}>
                  <button
                    type="button"
                    // Roving tabindex: the listbox is one tab stop, not 458 of
                    // them. Arrow keys already move the selection, so a Tab out
                    // of the search field closes this widget instead of walking
                    // a keyboard user through the whole catalogue.
                    tabIndex={-1}
                    data-active={index === active}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => pick(model.id)}
                    className={`flex w-full items-baseline justify-between gap-3 px-3 py-1.5 text-left ${
                      index === active ? "bg-slate-100" : ""
                    }`}
                  >
                    <span className="min-w-0 truncate font-mono text-[13px]">{model.id}</span>
                    <span className="shrink-0 text-xs text-slate-500">
                      {formatPrice(model.prompt_price)}
                      {model.context ? ` ${formatContext(model.context)}` : ""}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function SettingsPanel({ onSaved }: { onSaved: (state: SettingsState) => void }) {
  const [state, setState] = useState<SettingsState | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [key, setKey] = useState("");
  const [reveal, setReveal] = useState(false);
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [preset, setPreset] = useState("");
  const [extra, setExtra] = useState("");
  /** Set once the current address+key pair has been accepted by the provider.
   *  The model list is loaded from that provider, so there is nothing to pick
   *  from before that point -- showing an empty picker would only be noise. */
  const [keyOk, setKeyOk] = useState(false);
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad" | "idle"; text: string }>({ tone: "idle", text: "" });
  const selected = useMemo(() => models.find((m) => m.id === model), [models, model]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const loaded = await getSettings();
        if (!alive) return;
        setState(loaded);
        setModel(loaded.model);
        setBaseUrl(loaded.base_url);
        setPreset(loaded.preset);
        setExtra(loaded.extra);
        // A key is already on file, so its catalogue can be fetched straight away.
        if (loaded.has_key) {
          setKeyOk(true);
          try {
            setModels(await getModels());
          } catch {
            /* каталог не обязателен: провайдер может его не отдавать */
          }
        }
      } catch (error) {
        if (alive) setMessage({ tone: "bad", text: `Не удалось загрузить настройки: ${(error as Error).message}` });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const check = async (remember: boolean) => {
    setBusy("check");
    setMessage({ tone: "idle", text: "" });
    try {
      const result = await verifyKey(key, baseUrl, remember);
      if (result.ok) {
        setKeyOk(true);
        if (remember && result.settings) {
          setState(result.settings);
          setModel(result.settings.model);
          onSaved(result.settings);
        }
        // The catalogue belongs to whichever provider answered, so it is only
        // meaningful once that provider has accepted the key.
        try {
          setModels(await getModels());
        } catch (error) {
          setMessage({
            tone: "bad",
            text: "Ключ рабочий, но список моделей получить не удалось. Впишите название модели вручную.",
          });
          return;
        }
      } else {
        setKeyOk(false);
      }
      setMessage({ tone: result.ok ? "ok" : "bad", text: result.detail });
    } catch (error) {
      setKeyOk(false);
      setMessage({ tone: "bad", text: (error as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy("save");
    setMessage({ tone: "idle", text: "" });
    try {
      const result = await saveSettings(key, model, baseUrl, preset, extra);
      setState(result.settings);
      setKey("");
      onSaved(result.settings);
      setMessage({ tone: result.ok ? "ok" : "bad", text: result.detail });
    } catch (error) {
      setMessage({ tone: "bad", text: (error as Error).message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <Section label="Сервис для текста">
        <input
          value={baseUrl}
          onChange={(event) => {
            setBaseUrl(event.target.value);
            setKeyOk(false);
          }}
          spellCheck={false}
          placeholder="https://openrouter.ai/api/v1"
          aria-label="Адрес сервиса"
          className="focus-ring w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
        />
        <p className="mt-2 text-xs text-slate-500">
          Можно указать любой совместимый сервис. Сменили адрес, введите ключ заново.
        </p>
      </Section>

      <Section label="Ключ">
        <div className="flex flex-wrap gap-2">
          <input
            id="api-key"
            type={reveal ? "text" : "password"}
            value={key}
            autoComplete="off"
            spellCheck={false}
            aria-label="Ключ API"
            placeholder={
              state?.has_key
                ? `сохранён ${state.key_hint}. Вставьте новый, чтобы заменить`
                : "вставьте ключ сюда"
            }
            onChange={(event) => setKey(event.target.value)}
            className="focus-ring w-full min-w-[12rem] flex-1 rounded border border-slate-300 px-3 py-2 font-mono text-sm"
          />
          <Button variant="ghost" onClick={() => setReveal((r) => !r)} ariaLabel={reveal ? "Скрыть ключ" : "Показать ключ"}>
            {reveal ? <EyeOff aria-hidden className="h-4 w-4" /> : <Eye aria-hidden className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          {state?.has_key ? "Ключ сохранён, заново вводить его не нужно." : "Ключ пока не задан."}{" "}
          <a className="text-blue-700 underline" href={state?.key_page ?? "https://openrouter.ai/keys"} target="_blank" rel="noreferrer">
            Получить ключ
          </a>
        </p>
      </Section>

      <Section label="Какая модель отвечает">
        {keyOk ? (
          <>
            <ModelPicker models={models} value={model} onChange={setModel} />
            {models.length === 0 ? (
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="например gpt-4o-mini"
                aria-label="Название модели вручную"
                className="focus-ring mt-2 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
              />
            ) : null}
            <p className="mt-2 text-xs text-slate-600">
              {models.length
                ? `Доступно моделей: ${models.length}.`
                : "Сервис не показал список. Впишите название модели вручную."}
              {selected && selected.context ? ` За раз помещается около ${formatContext(selected.context)} знаков текста.` : ""}
            </p>
          </>
        ) : (
          <div className="rounded border border-dashed border-slate-300 px-3 py-4 text-sm text-slate-500">
            Введите адрес и ключ выше и нажмите «Проверить ключ». После проверки появится список моделей.
          </div>
        )}
      </Section>

      <Section label="Как собирать выжимку">
        {/* Один селектор на всё приложение. Здесь жил второй, написанный
            отдельно, и именно он остался без тёмного переопределения текста:
            выбранный режим в тёмной теме читался как тёмное по тёмному. */}
        <PresetPicker presets={state?.presets ?? []} value={preset} onChange={setPreset} name="settings-preset" />
        {/* Always available, and tall enough for a real prompt: picking a preset
            and adding to it are the same action, so there is no "Своё" option. */}
        <textarea
          value={extra}
          onChange={(event) => setExtra(event.target.value)}
          rows={3}
          placeholder="Свои требования, если нужно что-то ещё: например «выдели только договорённости по деньгам и срокам»"
          aria-label="Свои требования к выжимке"
          className="focus-ring mt-3 w-full resize-y rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <p className="mt-2 text-xs text-slate-600">
          Инструкции о персональных данных остаются в силе при любом выборе.
        </p>
      </Section>

      {message.text ? (
        <p className={`text-sm ${message.tone === "ok" ? "text-slate-700" : message.tone === "bad" ? "text-red-700" : "text-slate-600"}`}>
          {message.text}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void save()} disabled={busy !== null || (!key && !model && !baseUrl)}>
          {busy === "save" ? "Сохраняем…" : "Сохранить"}
        </Button>
        <Button variant="ghost" onClick={() => void check(false)} disabled={!key || busy !== null}>
          {busy === "check" ? "Проверяем…" : "Проверить ключ"}
        </Button>
      </div>
    </div>
  );
}