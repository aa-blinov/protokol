<script lang="ts">
  /** The check that stands between the recording and the provider.
   *
   *  The app's whole promise is that personal data is stripped on this machine,
   *  and nothing else leaves. A promise nobody can inspect is a promise they have
   *  to take on faith -- so the masked text is shown in full here, before
   *  anything is sent, along with what the call will cost. Sending is a button
   *  press, not a side effect of dropping a file.
   *
   *  The decision sits in a bar that stays on screen. The text is long, and a
   *  send button that waits at the bottom of it is one people never reach. */
  import { createEventDispatcher } from "svelte";
  import { Button, Notice, SegmentedControl } from "@monos/ui";
  import { formatCount, formatMoney, humanDuration, pluralRu, tokens, useEstimate } from "../lib/format";
  import { chipClass } from "../lib/highlight";
  import Section from "./Section.svelte";
  import type { AnalysisResult, SettingsState } from "../api";

  /** Above this the preview is cut and the rest is one click away. An hour of
   *  conversation is a lot of text to put in front of someone before they have
   *  agreed to spend anything. */
  const PREVIEW_LIMIT = 3000;

  /** A masked token as the model wrote it: [PERSON_1], sometimes with a case
   *  tag the model added: [PERSON_1|gen]. The chip shows the token alone. */
  const MASKED_TOKEN = /\[([A-Z_]+_\d+)(?:\|[a-z]+)?\]/g;

  export let name = "";
  export let analysis: AnalysisResult;
  export let settings: SettingsState;
  export let preset = "";
  export let busy = false;

  const dispatch = createEventDispatcher<{
    preset: string;
    send: void;
    skip: void;
    openSettings: void;
  }>();

  /** Whether the whole masked text is shown, or only the first page of it. */
  let full = false;

  $: masked = analysis?.masked_text ?? "";
  $: entityMap = analysis?.entity_map ?? {};
  $: hidden = Object.keys(entityMap).length;
  $: long = masked.length > PREVIEW_LIMIT;
  $: speakers = new Set((analysis?.segments ?? []).map((segment) => segment.speaker)).size;
  $: modes = (settings?.presets ?? []).map((item) => ({ value: item.key, label: item.label }));
  $: focusLabel = settings?.presets?.find((item) => item.key === preset)?.label ?? "";
  $: canSend = !busy && Boolean(settings?.has_key);
  $: estimate = useEstimate(masked.length, settings?.model ?? "");
  $: preview = long && !full ? masked.slice(0, PREVIEW_LIMIT) : masked;
  $: pieces = splitMasked(preview);

  /** The masked text, cut at every token so the chips can be drawn. */
  function splitMasked(text: string): { text: string; token: string; type: string }[] {
    const parts: { text: string; token: string; type: string }[] = [];
    let last = 0;
    for (const match of text.matchAll(MASKED_TOKEN)) {
      const at = match.index ?? 0;
      if (at > last) parts.push({ text: text.slice(last, at), token: "", type: "" });
      const token = match[1];
      parts.push({ text: match[0], token, type: token.replace(/_\d+$/, "") });
      last = at + match[0].length;
    }
    if (last < text.length) parts.push({ text: text.slice(last), token: "", type: "" });
    return parts;
  }

  const onModeChange = (event: CustomEvent<{ value: string }>) => {
    dispatch("preset", event.detail.value);
  };
</script>

<article class="text-ink">
  <header>
    <h2 class="break-words text-2xl font-semibold tracking-tight text-ink">{name}</h2>
    <p class="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[12px] tabular-nums text-ink-muted">
      {humanDuration(analysis?.duration_sec ?? 0)}
      {#if speakers > 1}
        <span>{speakers} {pluralRu(speakers, "спикер", "спикера", "спикеров")}</span>
      {/if}
    </p>
  </header>

  <!-- The privacy step, stated once: the work is done and nothing has left yet. -->
  <Notice tone="success" title="Ничего не отправлено">
    {hidden > 0
      ? `Скрыто ${formatCount(hidden)} ${pluralRu(hidden, "значение", "значения", "значений")}. Это весь текст, который увидит модель.`
      : "Личных данных не найдено. Это весь текст, который увидит модель."}
  </Notice>

  <Section label="Что уйдёт в модель">
    {#if long && !full}
      <div class="mb-3 flex justify-end">
        <Button variant="quiet" size="sm" on:click={() => (full = true)}>Показать целиком</Button>
      </div>
    {/if}
    <div class="max-h-[26rem] overflow-y-auto rounded-ui border border-line bg-surface p-3">
      <p class="whitespace-pre-wrap text-[13px] leading-6 text-ink-soft">
        {#each pieces as piece}
          {#if piece.token}
            <mark class={chipClass(piece.type)} title="{piece.token} → {entityMap[piece.token] ?? ''}">
              {piece.token}
            </mark>
          {:else}
            <span>{piece.text}</span>
          {/if}
        {/each}
      </p>
      {#if long && !full}
        <p class="mt-2 text-xs text-ink-muted">…и ещё {formatCount(masked.length - PREVIEW_LIMIT)} знаков</p>
      {/if}
    </div>
  </Section>

  <Section label="Что выделить в выжимке">
    <div class="max-w-xl">
      <!-- The chosen mode is the one framed element on the screen; the control
           scrolls sideways on a narrow window rather than pushing the page. -->
      <div class="max-w-full overflow-x-auto">
        <SegmentedControl
          options={modes}
          value={preset}
          label="Что выбрать из разговора"
          disabled={busy}
          on:change={onModeChange}
        />
      </div>
      {#if settings?.extra}
        <p class="mt-3 border-l border-line pl-3 text-xs text-ink-soft">
          Плюс ваше требование: «{settings.extra}»
        </p>
      {/if}
    </div>
  </Section>

  <div class="no-print sticky bottom-0 z-10 mt-10 border-t border-line bg-canvas py-3">
    <div class="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:gap-x-4">
      <p class="min-w-0 flex-1 basis-full text-xs text-ink-soft md:basis-auto">
        {#if settings?.has_key}
          <span class="text-ink">{focusLabel}</span>
          {" · "}
          {#if $estimate}
            {@const price = $estimate.total === null ? null : formatMoney($estimate.total)}
            <span class="tabular-nums">
              {tokens($estimate.tokens_in)}{price ? `, примерно ${price}` : ""}
            </span>
          {:else if busy}
            <span>Считаем стоимость…</span>
          {/if}
        {:else}
          Без ключа модель не ответит. Расшифровка от этого не пострадает.
        {/if}
      </p>
      <div class="flex w-full flex-col-reverse gap-2 md:w-auto md:shrink-0 md:flex-row md:items-center md:gap-3">
        <Button variant="quiet" on:click={() => dispatch("skip")} disabled={busy}>
          Только расшифровка
        </Button>
        {#if settings?.has_key}
          <Button size="lg" on:click={() => dispatch("send")} disabled={!canSend}>
            {busy ? "Составляем…" : "Составить выжимку"}
          </Button>
        {:else}
          <Button size="lg" on:click={() => dispatch("openSettings")}>Открыть настройки</Button>
        {/if}
      </div>
    </div>
  </div>
</article>
