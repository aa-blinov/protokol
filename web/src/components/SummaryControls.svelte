<script lang="ts">
  /** The controls around a finished summary: change the mode, make it again,
   *  and what the last one cost.
   *
   *  Every summary made for a recording stays reachable: a made mode shows its
   *  own result, an unmade one asks for it. Choosing a mode here never throws
   *  another one away -- the summaries are filed under the mode they were made
   *  in, so switching is a move, not a replacement. */
  import { createEventDispatcher } from "svelte";
  import { Button } from "@monos/ui";
  import { ChevronDown, RefreshCw } from "lucide-svelte";
  import ActualCostLine from "./ActualCostLine.svelte";
  import type { SettingsState, SummarizeResult } from "../api";

  export let settings: SettingsState;
  /** Every summary made for this recording, one entry per mode. */
  export let summaries: Record<string, SummarizeResult> = {};
  /** The summary on screen. */
  export let summary: SummarizeResult | null = null;
  /** The mode whose summary is on screen. */
  export let mode = "";
  export let busy = false;
  /** Whether the compose gate is open under these controls. */
  export let open = false;

  const dispatch = createEventDispatcher<{
    preset: string;
    run: void;
  }>();

  $: made = Object.keys(summaries ?? {});
  $: shown = mode && made.includes(mode) ? mode : (made[made.length - 1] ?? "");
</script>

<!-- One chip per mode, so every summary stays reachable: a made mode shows its
     own result, an unmade one opens the compose form for that mode. -->
{#if settings?.presets?.length}
  <div class="no-print mb-5 flex flex-wrap items-center gap-2">
    <span class="text-xs text-ink-muted">Выжимки по режимам:</span>
    {#each settings.presets as item (item.key)}
      {@const done = made.includes(item.key)}
      {@const active = item.key === shown}
      <Button
        variant={active ? "primary" : done ? "secondary" : "quiet"}
        size="sm"
        aria-current={active ? "true" : undefined}
        title={done ? undefined : "Выжимка в этом режиме ещё не составлена"}
        disabled={busy}
        on:click={() => dispatch("preset", item.key)}
      >
        {item.label}
      </Button>
    {/each}
  </div>
{/if}

<!-- What the last summary cost belongs beside the control that would spend
     again, not in the section label where it competed with the heading. -->
<div class="no-print flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line pt-3">
  <Button variant="quiet" size="sm" aria-expanded={open} on:click={() => dispatch("run")}>
    <svelte:fragment slot="icon">
      <RefreshCw size={14} aria-hidden="true" />
    </svelte:fragment>
    Изменить выжимку
    <svelte:fragment slot="trailing">
      <ChevronDown size={14} class={open ? "rotate-180" : ""} aria-hidden="true" />
    </svelte:fragment>
  </Button>
  <ActualCostLine
    cost={summary?.cost ?? { input: null, output: null, total: null }}
    tokensIn={summary?.tokens_in ?? null}
    tokensOut={summary?.tokens_out ?? null}
  />
</div>
