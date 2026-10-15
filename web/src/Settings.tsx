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
  activateLicence,
  getHealth,
  getLicence,
  getModels,
  getSettings,
  saveSettings,
  verifyKey,
  type HealthState,
  type LicenceState,
  type ModelInfo,
  type SettingsState,
} from "./api";
import { Button, FIELD, Section } from "./ui";
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

/** Services worth offering, with a model to start from and the shape of their key.
 *
 *  Addresses and key prefixes are stable facts about each service. The model
 *  here is only a starting point: the list in «Какая модель отвечает» comes
 *  live from the service itself, so a stale suggestion is corrected by picking
 *  from the real list rather than by editing code.
 *
 *  Anything not listed still works -- the address below stays editable for a
 *  self-hosted endpoint or a service that appears later. */
const SERVICES: {
  id: string;
  label: string;
  baseUrl: string;
  model: string;
  keyHint: string;
  keyPage: string;
}[] = [
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    model: "deepseek/deepseek-v4.1-flash",
    keyHint: "sk-or-v1-…",
    keyPage: "https://openrouter.ai/keys",
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-5.4-mini",
    keyHint: "sk-proj-… или sk-…",
    keyPage: "https://platform.openai.com/api-keys",
  },
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    baseUrl: "https://api.anthropic.com/v1",
    model: "claude-sonnet-5",
    keyHint: "sk-ant-…",
    keyPage: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    model: "gemini-3.8-flash",
    keyHint: "AIza…",
    keyPage: "https://aistudio.google.com/apikey",
  },
  {
    id: "groq",
    label: "Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    model: "openai/gpt-oss-120b",
    keyHint: "gsk_…",
    keyPage: "https://console.groq.com/keys",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-flash",
    keyHint: "sk-…",
    keyPage: "https://platform.deepseek.com/api_keys",
  },
];

const matchService = (baseUrl: string) =>
  SERVICES.find((s) => s.baseUrl === baseUrl.trim().replace(/\/+$/, "")) ?? null;

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
        className={`${FIELD} flex w-full items-center justify-between gap-3 text-left text-sm hover:bg-stone-50`}
      >
        <span className="min-w-0 truncate font-mono text-[13px]">
          {selected ? selected.id : <span className="text-stone-500">Модель не выбрана</span>}
        </span>
        <Search aria-hidden className="h-4 w-4 shrink-0 text-stone-500" />
      </button>

      {open ? (
        <div className="absolute z-30 mt-1 w-full min-w-0 max-w-full overflow-hidden rounded border border-stone-300 bg-sheet">
          <div className="border-b border-stone-200 p-2">
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
              // stone-400 border on stone-200 is far too quiet to navigate by.
              // focus: also fires on mouse press, which is the wrong way round.
              className="focus-ring w-full rounded border border-stone-200 px-2 py-1.5 font-mono text-[13px] focus:border-stone-400"
            />
          </div>
          <ul ref={listRef} role="listbox" className="max-h-64 overflow-y-auto py-1">
            {matches.length === 0 ? (
              <li className="px-3 py-3 text-sm text-stone-500">Ничего не найдено</li>
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
                      index === active ? "bg-stone-100" : ""
                    }`}
                  >
                    <span className="min-w-0 truncate font-mono text-[13px]">{model.id}</span>
                    <span className="shrink-0 text-xs text-stone-500">
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

/** One sentence about the licence, in the words the customer needs. */
function licenceLine(licence: LicenceState): string {
  if (licence.state === "licensed") {
    const who = [
      licence.customer,
      licence.edition ? `издание ${licence.edition}` : null,
      licence.seats ? `мест: ${licence.seats}` : null,
    ]
      .filter(Boolean)
      .join(", ");
    return licence.expires ? `Лицензия: ${who}, до ${licence.expires}.` : `Лицензия: ${who}, бессрочно.`;
  }
  if (licence.state === "trial") return `Пробный период: осталось ${licence.days_left} дн.`;
  return `${licence.problem || "Лицензия не действует"}. Расшифровка и выжимка остановлены; история доступна.`;
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
  const service = useMemo(() => matchService(baseUrl), [baseUrl]);
  /** The key stored for whichever service is on screen — the backend never
   *  sends the key itself, only enough of it to tell two apart. */
  const savedHint = service ? state?.saved_keys?.[service.baseUrl] : state?.key_hint;
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "bad" | "idle"; text: string }>({ tone: "idle", text: "" });
  const selected = useMemo(() => models.find((m) => m.id === model), [models, model]);
  const [retention, setRetention] = useState("0");
  const [licence, setLicence] = useState<LicenceState | null>(null);
  const [health, setHealth] = useState<HealthState | null>(null);
  // What the organisation fixed. A locked field is disabled, not hidden, so the
  // person can see what is set and why it cannot be changed here.
  const locked = state?.policy.lock_settings ?? false;
  const baseLocked = state?.policy.base_url_locked ?? false;
  const retentionLocked = (state?.policy.retention_days ?? null) !== null;

  const installLicence = async (file: File | undefined) => {
    if (!file) return;
    try {
      setLicence(await activateLicence(await file.text()));
      setMessage({ tone: "ok", text: "Лицензия установлена" });
    } catch (error) {
      setMessage({ tone: "bad", text: (error as Error).message });
    }
  };

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
        setRetention(String(loaded.retention_days ?? 0));
        void getLicence().then((value) => { if (alive) setLicence(value); }).catch(() => undefined);
        void getHealth().then((value) => { if (alive) setHealth(value); }).catch(() => undefined);
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
      const days = Math.max(0, Math.floor(Number(retention) || 0));
      const result = await saveSettings(key, model, baseUrl, preset, extra, retentionLocked ? null : days);
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
      {state?.policy.managed ? (
        <div className="rounded border border-stone-300 bg-stone-100 px-3 py-2 text-sm text-stone-700">
          Настройки задаёт организация{locked ? ": изменить их в приложении нельзя" : ""}.
          {state.policy.errors.length ? (
            <span className="mt-1 block text-xs text-red-700">
              Не применено из файла политики: {state.policy.errors.join("; ")}.
            </span>
          ) : null}
        </div>
      ) : null}
      <fieldset disabled={locked} className="space-y-6">
      <Section label="Сервис для текста">
        <select
          disabled={baseLocked}
          value={service?.id ?? "custom"}
          onChange={(event) => {
            const picked = SERVICES.find((s) => s.id === event.target.value);
            if (!picked) return;
            setBaseUrl(picked.baseUrl);
            setModel(picked.model);
            setKey("");
            setKeyOk(false);
            setModels([]);
          }}
          aria-label="Сервис для текста"
          // The height is spelled out because Chrome sizes <select> from its own
          // inner box: the same padding that makes every other field 38px leaves
          // this one at 37. Not visible side by side, but the fields below are a
          // set, and a set that is a pixel off is a set that looks unfinished.
          className={`${FIELD} h-[38px] w-full text-sm`}
        >
          {!service ? (
            <option value="custom">Другой адрес</option>
          ) : null}
          {SERVICES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
              {state?.saved_keys?.[s.baseUrl] ? " (ключ сохранён)" : ""}
            </option>
          ))}
        </select>

        <input
          disabled={baseLocked}
          value={baseUrl}
          onChange={(event) => {
            setBaseUrl(event.target.value);
            setKeyOk(false);
          }}
          spellCheck={false}
          placeholder="https://openrouter.ai/api/v1"
          aria-label="Адрес сервиса"
          className={`${FIELD} mt-2 w-full font-mono text-sm`}
        />
        <p className="mt-2 text-xs text-stone-500">
          {service
            ? `Ключ этого сервиса начинается с ${service.keyHint}.`
            : "Свой адрес: подойдёт любой сервис с OpenAI-совместимым API."}{" "}
          Ключ каждого сервиса хранится отдельно и не теряется при переключении.
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
              savedHint
                ? `сохранён ${savedHint}. Вставьте новый, чтобы заменить`
                : service
                  ? `ключ ${service.keyHint}, вставьте сюда`
                  : "вставьте ключ сюда"
            }
            onChange={(event) => setKey(event.target.value)}
            className={`${FIELD} w-full min-w-[12rem] flex-1 font-mono text-sm`}
          />
          {/* 38 px to match the key field beside it, same reason as in the
              document toolbar: 36 centres one pixel lower and the pair reads
              as two controls of different sizes. */}
          <Button
            variant="ghost"
            className="min-h-[38px]"
            onClick={() => setReveal((r) => !r)}
            ariaLabel={reveal ? "Скрыть ключ" : "Показать ключ"}
          >
            {reveal ? <EyeOff aria-hidden className="h-4 w-4" /> : <Eye aria-hidden className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-2 text-xs text-stone-500">
          {savedHint ? "Ключ сохранён, заново вводить его не нужно." : "Ключ пока не задан."}{" "}
          <a className="text-accent-700 underline" href={service?.keyPage ?? state?.key_page ?? "https://openrouter.ai/keys"} target="_blank" rel="noreferrer">
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
                className={`${FIELD} mt-2 w-full font-mono text-sm`}
              />
            ) : null}
            <p className="mt-2 text-xs text-stone-600">
              {models.length
                ? `Доступно моделей: ${models.length}.`
                : "Сервис не показал список. Впишите название модели вручную."}
              {selected && selected.context ? ` За раз помещается около ${formatContext(selected.context)} знаков текста.` : ""}
            </p>
          </>
        ) : (
          <div className="rounded border border-dashed border-stone-300 px-3 py-4 text-sm text-stone-500">
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
          className={`${FIELD} mt-3 w-full resize-y text-sm`}
        />
        <p className="mt-2 text-xs text-stone-600">
          Инструкции о персональных данных остаются в силе при любом выборе.
        </p>
      </Section>

      </fieldset>

      <fieldset disabled={locked || retentionLocked}>
        <Section label="Срок хранения истории">
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="number"
              min={0}
              max={3650}
              value={retention}
              onChange={(event) => setRetention(event.target.value)}
              aria-label="Срок хранения, дней"
              className={`${FIELD} w-28 text-sm`}
            />
            <span className="text-sm text-stone-600">дней; 0 — не удалять</span>
          </div>
          <p className="mt-2 text-xs text-stone-500">
            {retentionLocked
              ? `Срок задан организацией: ${state?.policy.retention_days} дн.`
              : "Записи старше срока удаляются вместе с расшифровкой и кэшем."}
          </p>
          {health && health.filevault === false ? (
            <p className="mt-2 text-xs text-red-700">
              FileVault выключен: данные на диске не зашифрованы системой. Включите его в Системных
              настройках, в разделе «Конфиденциальность и безопасность».
            </p>
          ) : null}
        </Section>
      </fieldset>

      <Section label="Лицензия">
        <p className="text-sm text-stone-700">
          {licence ? licenceLine(licence) : "Состояние лицензии загружается…"}
        </p>
        <input
          type="file"
          accept=".json,.license,application/json"
          aria-label="Файл лицензии"
          onChange={(event) => void installLicence(event.target.files?.[0])}
          className="mt-2 text-sm"
        />
      </Section>

      {message.text ? (
        <p className={`text-sm ${message.tone === "ok" ? "text-stone-700" : message.tone === "bad" ? "text-red-700" : "text-stone-600"}`}>
          {message.text}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void save()} disabled={locked || busy !== null || (!key && !model && !baseUrl)}>
          {busy === "save" ? "Сохраняем…" : "Сохранить"}
        </Button>
        <Button variant="ghost" onClick={() => void check(false)} disabled={locked || !key || busy !== null}>
          {busy === "check" ? "Проверяем…" : "Проверить ключ"}
        </Button>
      </div>
    </div>
  );
}