<script lang="ts">
  import { createEventDispatcher, onMount } from "svelte";
  import {
    Button,
    Combobox,
    Fieldset,
    IconButton,
    Notice,
    RadioGroup,
    SelectField,
    TextArea,
    TextField,
  } from "@monos/ui";
  import { Eye, EyeOff } from "lucide-svelte";
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
  } from "../api";
  import Section from "./Section.svelte";

  const dispatch = createEventDispatcher<{ saved: SettingsState }>();

  /** A service worth offering, with a model to start from and the shape of its key.
   *
   *  Addresses and key prefixes are stable facts about each service. The model
   *  here is only a starting point: the list in «Какая модель отвечает» comes
   *  live from the service itself, so a stale suggestion is corrected by picking
   *  from the real list rather than by editing code.
   *
   *  Anything not listed still works -- the address below stays editable for a
   *  self-hosted endpoint or a service that appears later. */
  interface Service {
    id: string;
    label: string;
    baseUrl: string;
    model: string;
    keyHint: string;
    keyPage: string;
  }

  const SERVICES: Service[] = [
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

  const matchService = (baseUrl: string): Service | null =>
    SERVICES.find((s) => s.baseUrl === baseUrl.trim().replace(/\/+$/, "")) ?? null;

  /** The model window as a person reads it: "128K", "1M". */
  function formatContext(value: number | null): string {
    if (!value) return "";
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(0)}M`;
    return `${Math.round(value / 1000)}K`;
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

  let state: SettingsState | null = null;
  let models: ModelInfo[] = [];
  let key = "";
  let reveal = false;
  let model = "";
  let baseUrl = "";
  let preset = "";
  let extra = "";
  /** Set once the current address+key pair has been accepted by the provider.
   *  The model list is loaded from that provider, so there is nothing to pick
   *  from before that point -- showing an empty picker would only be noise. */
  let keyOk = false;
  let busy: "check" | "save" | null = null;
  let message: { tone: "ok" | "bad" | "idle"; text: string } = { tone: "idle", text: "" };
  let retention = "0";
  let licence: LicenceState | null = null;
  let health: HealthState | null = null;

  $: service = matchService(baseUrl);
  /** The key stored for whichever service is on screen -- the backend never
   *  sends the key itself, only enough of it to tell two apart. */
  $: savedHint = service ? state?.saved_keys?.[service.baseUrl] : state?.key_hint;
  $: selected = models.find((m) => m.id === model);
  // What the organisation fixed. A locked field is disabled, not hidden, so the
  // person can see what is set and why it cannot be changed here.
  $: locked = state?.policy.lock_settings ?? false;
  $: baseLocked = state?.policy.base_url_locked ?? false;
  $: retentionLocked = (state?.policy.retention_days ?? null) !== null;
  $: serviceOptions = [
    ...(service ? [] : [{ value: "custom", label: "Другой адрес" }]),
    ...SERVICES.map((s) => ({
      value: s.id,
      label: s.label + (state?.saved_keys?.[s.baseUrl] ? " (ключ сохранён)" : ""),
    })),
  ];
  $: modelOptions = models.map((m) => ({ value: m.id, label: m.id }));
  $: presetOptions = (state?.presets ?? []).map((p) => ({ value: p.key, label: p.label }));

  onMount(() => {
    let alive = true;
    void (async () => {
      try {
        const loaded = await getSettings();
        if (!alive) return;
        state = loaded;
        model = loaded.model;
        baseUrl = loaded.base_url;
        preset = loaded.preset;
        extra = loaded.extra;
        retention = String(loaded.retention_days ?? 0);
        void getLicence()
          .then((value) => {
            if (alive) licence = value;
          })
          .catch(() => undefined);
        void getHealth()
          .then((value) => {
            if (alive) health = value;
          })
          .catch(() => undefined);
        // A key is already on file, so its catalogue can be fetched straight away.
        if (loaded.has_key) {
          keyOk = true;
          try {
            models = await getModels();
          } catch {
            /* the catalogue is optional: a provider may not serve one */
          }
        }
      } catch (error) {
        if (alive) {
          message = { tone: "bad", text: `Не удалось загрузить настройки: ${(error as Error).message}` };
        }
      }
    })();
    return () => {
      alive = false;
    };
  });

  async function check(remember: boolean): Promise<void> {
    busy = "check";
    message = { tone: "idle", text: "" };
    try {
      const result = await verifyKey(key, baseUrl, remember);
      if (result.ok) {
        keyOk = true;
        if (remember && result.settings) {
          state = result.settings;
          model = result.settings.model;
          dispatch("saved", result.settings);
        }
        // The catalogue belongs to whichever provider answered, so it is only
        // meaningful once that provider has accepted the key.
        try {
          models = await getModels();
        } catch {
          message = {
            tone: "bad",
            text: "Ключ рабочий, но список моделей получить не удалось. Впишите название модели вручную.",
          };
          return;
        }
      } else {
        keyOk = false;
      }
      message = { tone: result.ok ? "ok" : "bad", text: result.detail };
    } catch (error) {
      keyOk = false;
      message = { tone: "bad", text: (error as Error).message };
    } finally {
      busy = null;
    }
  }

  async function save(): Promise<void> {
    busy = "save";
    message = { tone: "idle", text: "" };
    try {
      const days = Math.max(0, Math.floor(Number(retention) || 0));
      const result = await saveSettings(key, model, baseUrl, preset, extra, retentionLocked ? null : days);
      state = result.settings;
      key = "";
      dispatch("saved", result.settings);
      message = { tone: result.ok ? "ok" : "bad", text: result.detail };
    } catch (error) {
      message = { tone: "bad", text: (error as Error).message };
    } finally {
      busy = null;
    }
  }

  async function installLicence(file: File | undefined): Promise<void> {
    if (!file) return;
    try {
      licence = await activateLicence(await file.text());
      message = { tone: "ok", text: "Лицензия установлена" };
    } catch (error) {
      message = { tone: "bad", text: (error as Error).message };
    }
  }

  function onServiceChange(event: Event): void {
    const picked = SERVICES.find((s) => s.id === (event.currentTarget as HTMLSelectElement).value);
    if (!picked) return;
    baseUrl = picked.baseUrl;
    model = picked.model;
    key = "";
    keyOk = false;
    models = [];
  }

  function onBaseUrlInput(): void {
    keyOk = false;
  }

  function onLicenceFile(event: Event): void {
    const input = event.currentTarget as HTMLInputElement;
    void installLicence(input.files?.[0]);
  }

  function toggleReveal(): void {
    reveal = !reveal;
  }

  function checkKey(): void {
    void check(false);
  }
</script>

<section id="settings-panel" aria-label="Настройки" class="text-ink">
  {#if state?.policy.managed}
    <Notice tone="warning">
      Настройки задаёт организация{locked ? ": изменить их в приложении нельзя" : ""}.
    </Notice>
    {#if state.policy.errors.length}
      <div class="mt-3">
        <Notice tone="danger">
          Не применено из файла политики: {state.policy.errors.join("; ")}.
        </Notice>
      </div>
    {/if}
  {/if}

  <Fieldset disabled={locked}>
    <Section label="Сервис для текста">
      <SelectField
        value={service?.id ?? "custom"}
        options={serviceOptions}
        disabled={locked || baseLocked}
        variant="boxed"
        aria-label="Сервис для текста"
        on:change={onServiceChange}
      />

      <div class="mt-2">
        <TextField
          bind:value={baseUrl}
          disabled={locked || baseLocked}
          variant="boxed"
          placeholder="https://openrouter.ai/api/v1"
          aria-label="Адрес сервиса"
          spellcheck={false}
          on:input={onBaseUrlInput}
        />
      </div>
      <p class="mt-2 text-xs text-ink-faint">
        {service
          ? `Ключ этого сервиса начинается с ${service.keyHint}.`
          : "Свой адрес: подойдёт любой сервис с OpenAI-совместимым API."}{" "}
        Ключ каждого сервиса хранится отдельно и не теряется при переключении.
      </p>
    </Section>

    <Section label="Ключ">
      <div class="flex flex-wrap gap-2">
        <div class="min-w-[12rem] flex-1">
          <TextField
            id="api-key"
            bind:value={key}
            type={reveal ? "text" : "password"}
            disabled={locked}
            variant="boxed"
            autocomplete="off"
            spellcheck={false}
            aria-label="Ключ API"
            placeholder={savedHint
              ? `сохранён ${savedHint}. Вставьте новый, чтобы заменить`
              : service
                ? `ключ ${service.keyHint}, вставьте сюда`
                : "вставьте ключ сюда"}
          />
        </div>
        <IconButton
          variant="ghost"
          label={reveal ? "Скрыть ключ" : "Показать ключ"}
          disabled={locked}
          on:click={toggleReveal}
        >
          {#if reveal}
            <EyeOff size={16} strokeWidth={1.7} aria-hidden="true" />
          {:else}
            <Eye size={16} strokeWidth={1.7} aria-hidden="true" />
          {/if}
        </IconButton>
      </div>
      <p class="mt-2 text-xs text-ink-faint">
        {savedHint ? "Ключ сохранён, заново вводить его не нужно." : "Ключ пока не задан."}{" "}
        <a
          class="text-accent-text underline"
          href={service?.keyPage ?? state?.key_page ?? "https://openrouter.ai/keys"}
          target="_blank"
          rel="noreferrer">Получить ключ</a
        >
      </p>
    </Section>

    <Section label="Какая модель отвечает">
      {#if keyOk}
        <Combobox
          bind:value={model}
          options={modelOptions}
          disabled={locked}
          placeholder="Модель не выбрана"
          emptyLabel="Ничего не найдено"
          clearLabel="Очистить"
        />
        {#if models.length === 0}
          <div class="mt-2">
            <TextField
              bind:value={model}
              disabled={locked}
              variant="boxed"
              placeholder="например gpt-4o-mini"
              aria-label="Название модели вручную"
            />
          </div>
        {/if}
        <p class="mt-2 text-xs text-ink-soft">
          {models.length
            ? `Доступно моделей: ${models.length}.`
            : "Сервис не показал список. Впишите название модели вручную."}
          {selected && selected.context
            ? ` За раз помещается около ${formatContext(selected.context)} знаков текста.`
            : ""}
        </p>
      {:else}
        <Notice tone="neutral">
          Введите адрес и ключ выше и нажмите «Проверить ключ». После проверки появится список моделей.
        </Notice>
      {/if}
    </Section>

    <Section label="Как собирать выжимку">
      <!-- One selector for the whole application. The second one, written apart,
          is the one that stayed without a dark override of its text: the chosen
          mode read as dark on dark. -->
      <RadioGroup
        bind:value={preset}
        options={presetOptions}
        name="settings-preset"
        label="Что выбрать из разговора"
        disabled={locked}
      />
      <!-- Always available, and tall enough for a real prompt: picking a preset
          and adding to it are the same action, so there is no "Своё" option. -->
      <div class="mt-3">
        <TextArea
          bind:value={extra}
          disabled={locked}
          variant="boxed"
          rows={3}
          placeholder="Свои требования, если нужно что-то ещё: например «выдели только договорённости по деньгам и срокам»"
          aria-label="Свои требования к выжимке"
        />
      </div>
      <p class="mt-2 text-xs text-ink-soft">
        Инструкции о персональных данных остаются в силе при любом выборе.
      </p>
    </Section>
  </Fieldset>

  <Fieldset disabled={locked || retentionLocked}>
    <Section label="Срок хранения истории">
      <div class="flex flex-wrap items-center gap-3">
        <div class="w-28">
          <TextField
            bind:value={retention}
            type="number"
            disabled={locked || retentionLocked}
            variant="boxed"
            min={0}
            max={3650}
            aria-label="Срок хранения, дней"
          />
        </div>
        <span class="text-sm text-ink-soft">дней; 0 — не удалять</span>
      </div>
      <p class="mt-2 text-xs text-ink-faint">
        {retentionLocked
          ? `Срок задан организацией: ${state?.policy.retention_days} дн.`
          : "Записи старше срока удаляются вместе с расшифровкой и кэшем."}
      </p>
      {#if health && health.filevault === false}
        <div class="mt-2">
          <Notice tone="danger">
            FileVault выключен: данные на диске не зашифрованы системой. Включите его в Системных
            настройках, в разделе «Конфиденциальность и безопасность».
          </Notice>
        </div>
      {/if}
    </Section>
  </Fieldset>

  <Section label="Лицензия">
    <p class="text-sm text-ink-soft">
      {licence ? licenceLine(licence) : "Состояние лицензии загружается…"}
    </p>
    <!-- The kit's FileUpload hides its own input from the accessibility tree and
         offers no way to name the drop zone, so the native control stays: the
         browser draws it, the screen reader names it, and the licence file is
         the one thing here that must not be lost. -->
    <input
      type="file"
      accept=".json,.license,application/json"
      aria-label="Файл лицензии"
      on:change={onLicenceFile}
      class="mt-2 block w-full text-sm text-ink-soft file:mr-3 file:rounded-ui file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-ink"
    />
  </Section>

  {#if message.text}
    <div class="mt-6">
      <Notice tone={message.tone === "ok" ? "success" : message.tone === "bad" ? "danger" : "neutral"}>
        {message.text}
      </Notice>
    </div>
  {/if}

  <div class="mt-6 flex flex-wrap items-center gap-2">
    <Button
      variant="primary"
      disabled={locked || busy !== null || (!key && !model && !baseUrl)}
      on:click={save}
    >
      {busy === "save" ? "Сохраняем…" : "Сохранить"}
    </Button>
    <Button variant="secondary" disabled={locked || !key || busy !== null} on:click={checkKey}>
      {busy === "check" ? "Проверяем…" : "Проверить ключ"}
    </Button>
  </div>
</section>
