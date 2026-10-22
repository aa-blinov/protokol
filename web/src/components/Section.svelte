<script lang="ts">
  /** A document section: a small mono label, an optional right-hand meta, a
   *  hairline above, and a body that can be folded away.
   *
   *  The label itself is the trigger, not a small link in the corner: a
   *  disclosure is a label that opens things, and a 12px «скрыть» on the right
   *  reads as another action competing with the ones beside it.
   *
   *  The button covers the heading only and `meta` stays a sibling. Wrapping
   *  the whole row put the section's «Скопировать» inside another button --
   *  invalid HTML, and the click that copied the text also folded the section. */
  import { createEventDispatcher } from "svelte";
  import ChevronDown from "lucide-svelte/icons/chevron-down";

  export let label = "";
  export let meta = "";
  export let collapsed = false;
  /** Shown instead of the body when collapsed, so the reader can tell what is
   *  in there without opening it. */
  export let collapsedNote = "";
  /** The label folds the body away. A component cannot ask who listens to its
   *  events, so this callback is also what makes the label a trigger. */
  export let onToggle: (() => void) | undefined = undefined;

  const dispatch = createEventDispatcher<{ toggle: void }>();

  const LABEL = "font-mono text-[12px] font-medium uppercase tracking-[0.12em]";

  function toggle() {
    onToggle?.();
    dispatch("toggle");
  }
</script>

<section class="mt-8 border-t border-line pt-5">
  <div class="mb-4 flex items-baseline justify-between gap-4">
    {#if onToggle}
      <h3>
        <button
          type="button"
          on:click={toggle}
          aria-expanded={!collapsed}
          class="flex cursor-pointer items-baseline gap-1.5 rounded-ui {LABEL} text-ink-muted hover:text-ink"
        >
          <ChevronDown
            size={14}
            strokeWidth={1.7}
            class="h-3.5 w-3.5 shrink-0 transition-transform {collapsed ? '-rotate-90' : ''}"
          />{label}<span class="sr-only">, {collapsed ? "развернуть" : "свернуть"}</span>
        </button>
      </h3>
    {:else}
      <h3 class="{LABEL} text-ink-muted">{label}</h3>
    {/if}
    {#if meta || $$slots.meta}
      <div class="no-print text-xs text-ink-muted"><slot name="meta">{meta}</slot></div>
    {/if}
  </div>
  {#if collapsed}
    {#if collapsedNote}
      <p class="text-xs text-ink-muted">{collapsedNote}</p>
    {/if}
  {:else}
    <slot />
  {/if}
</section>
