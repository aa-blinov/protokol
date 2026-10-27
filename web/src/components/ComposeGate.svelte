<script lang="ts">
  /** The one place a summary decision is made.
   *
   *  There used to be two: the pre-send review after a file loads, and a panel
   *  inside the finished document. They held the same controls but behaved
   *  differently -- one sent on click, the other asked first -- so the only way to
   *  learn which was safe was to try it. Same surface now, same words, same rule:
   *  the cost and the focus are shown before anything is sent, whatever brought
   *  you here.
   *
   *  It appears full-screen when there is no document yet, and in place inside the
   *  summary section when re-running one. Nothing is thrown away to get back here. */
  import { createEventDispatcher } from "svelte";
  import { Button, RadioGroup } from "@monos/ui";
  import { formatMoney, tokens } from "../lib/format";
  import type { EstimateResult, SettingsState } from "../api";

  export let settings: SettingsState;
  export let preset = "";
  export let estimate: EstimateResult | null = null;
  export let busy: "none" | "analysing" | "summarising" = "none";
  export let canRun = true;
  export let runLabel = "";
  /** The label of the button that leaves the gate without sending anything.
   *  Empty when the gate cannot be left: there is nothing to go back to. */
  export let closeLabel = "";

  const dispatch = createEventDispatcher<{
    preset: string;
    run: void;
    openSettings: void;
    close: void;
  }>();

  $: modes = (settings?.presets ?? []).map((item) => ({ value: item.key, label: item.label }));
  $: waiting = busy !== "none";
  $: price = estimate && estimate.total !== null ? formatMoney(estimate.total) : null;

  const onPresetChange = (event: CustomEvent<string>) => {
    dispatch("preset", event.detail);
  };
</script>

<div class="max-w-xl space-y-4">
  <!-- A real radio group: the name is shared, so the arrow keys move the way
       the browser moves radios. -->
  <RadioGroup
    options={modes}
    value={preset}
    name="preset"
    label="Что выбрать из разговора"
    disabled={waiting}
    on:change={onPresetChange}
  />

  {#if settings?.extra}
    <p class="border-l border-line pl-3 text-xs text-ink-soft">
      Плюс ваше требование: «{settings.extra}»
    </p>
  {/if}

  {#if waiting && !estimate}
    <p class="text-xs text-ink-muted">Считаем примерную стоимость…</p>
  {:else if estimate}
    <div class="space-y-1 text-xs text-ink-soft">
      <p class="tabular-nums">
        {tokens(estimate.tokens_in)} текста уйдёт в модель{estimate.requests > 1
          ? `, обращений к модели: ${estimate.requests}`
          : ""}{price ? `, примерно ${price}` : ""}
      </p>
      {#if estimate.requests > 1}
        <p class="text-ink-muted">
          Разговор длинный: текст сначала сжимается по частям, поэтому обращений к модели больше одного. После отправки
          покажем точную сумму.
        </p>
      {/if}
      {#if price === null}
        <p class="text-ink-muted">
          Стоимость зависит от провайдера и станет известна только после отправки.
        </p>
      {/if}
    </div>
  {/if}

  <div class="flex flex-wrap items-center gap-4">
    {#if settings?.has_key}
      <Button on:click={() => dispatch("run")} disabled={waiting || !canRun} size="lg">
        {waiting ? "Составляем…" : runLabel}
      </Button>
    {:else}
      <Button on:click={() => dispatch("openSettings")} size="lg">Открыть настройки</Button>
    {/if}
    {#if closeLabel}
      <Button variant="quiet" on:click={() => dispatch("close")} disabled={waiting}>{closeLabel}</Button>
    {/if}
  </div>

  {#if !settings?.has_key}
    <p class="text-xs text-ink-muted">Без ключа модель не ответит. Расшифровка от этого не пострадает.</p>
  {:else if !canRun}
    <p class="text-xs text-ink-muted">
      Расшифровка этой записи больше не сохранена. Загрузите файл заново, это займёт столько же времени.
    </p>
  {/if}
</div>
