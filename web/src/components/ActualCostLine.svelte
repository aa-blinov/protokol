<script lang="ts">
  /** What the last summary actually cost, from the counts the provider reported.
   *
   *  The figure sits beside the control that would spend again, not in the
   *  section label where it competed with the heading for the same band. */
  import { formatMoney, tokens } from "../lib/format";

  export let cost: { input: number | null; output: number | null; total: number | null } = {
    input: null,
    output: null,
    total: null,
  };
  export let tokensIn: number | null = null;
  export let tokensOut: number | null = null;
</script>

{#if cost.total === null}
  {#if tokensIn !== null}
    <p class="tabular-nums text-xs text-ink-muted">
      {tokens(tokensIn)} в модель, {tokens(tokensOut ?? 0)} обратно
    </p>
  {/if}
{:else}
  <p class="tabular-nums text-xs text-ink-muted">
    {formatMoney(cost.total)}, {tokens(tokensIn ?? 0)} в модель, {tokens(tokensOut ?? 0)} обратно
  </p>
{/if}
