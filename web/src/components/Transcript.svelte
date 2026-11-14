<script lang="ts">
  /** The transcript: the speaker turns, their clocks, the personal-data chips
   *  and the search that has to work on an hour-long recording.
   *
   *  A meeting transcript is several screens of scrolling and nobody re-reads it
   *  linearly -- people go back to it for one thing they half-remember being
   *  said. Search is over the original text, not the masked copy, because the
   *  person searching wants the words that were spoken; the personal-data chips
   *  stay visible underneath so it is still obvious what would be hidden.
   *
   *  The whole transcript is rendered. It used to stop at the first screen with
   *  a «Показать целиком» underneath, which was a second way of saying «тут есть
   *  ещё» next to the section arrow that now does the one job. */
  import { createEventDispatcher, tick } from "svelte";
  import type { AnalysisResult } from "../api";
  import {MAX_HITS, chipClass, clock, split, type Hit, type Piece, within } from "../lib/highlight";

  export let analysis: AnalysisResult;
  export let query = "";
  export let hits: Hit[] = [];
  export let cursor = 0;

  const dispatch = createEventDispatcher<{ query: string; step: number }>();

  /** The cap `lib/highlight.ts` stops counting at. The constant is not exported
   *  there, so the number is repeated here: the note under the field must not
   *  promise more matches than the search can see. */

  /** One speaker turn, or the whole transcript when there are no turns. */
  type Turn = {
    speaker: number | null;
    start: number;
    parts: Piece[];
  };

  let root: HTMLDivElement | null = null;

  $: turns = buildTurns(analysis, hits);

  /** The turns of the recording, with their chips and their hits already
   *  shifted into the turn's own slice of the text. */
  function buildTurns(analysis: AnalysisResult, hits: Hit[]): Turn[] {
    if (!analysis.segments.length) {
      return [
        {
          speaker: null,
          start: 0,
          parts: split(analysis.transcript, analysis.entities, hits),
        },
      ];
    }
    return analysis.segments.map((segment) => {
      const from = segment.offset;
      const to = from + segment.text.length;
      // Absolute hits shifted into this turn's own slice, keeping each one's
      // place in the whole transcript so "current" stays meaningful.
      const inside = hits
        .map((hit, position) => ({ ...hit, index: position }))
        .filter((hit) => hit.start >= from && hit.end <= to)
        .map((hit) => ({ start: hit.start - from, end: hit.end - from, index: hit.index }));
      return {
        speaker: segment.speaker,
        start: segment.start,
        parts: split(segment.text, within(analysis.entities, from, segment.text.length), inside),
      };
    });
  }




  function step(direction: number) {
    if (!hits.length) return;
    dispatch("step", direction);
  }

  // Bring the current match into view. Selected by attribute rather than by a
  // ref, because a match can land inside a personal-data chip and then there is
  // no dedicated element to hang one on.
  $: if (root && hits.length) {
    void scrollToHit(cursor);
  }

  async function scrollToHit(at: number) {
    await tick();
    root?.querySelector(`[data-hit="${at}"]`)?.scrollIntoView({ block: "center", behavior: "auto" });
  }
</script>

{#if query && hits.length >= MAX_HITS}
  <p class="mb-3 mt-4 text-xs text-ink-muted">Показаны первые {MAX_HITS} совпадений. Дополните запрос, чтобы сузить поиск.</p>
{/if}

<div bind:this={root}>
  <ul class="space-y-5">
    {#each turns as turn, index (index)}
      <li class={turn.speaker === null ? "" : "grid grid-cols-[92px_1fr] gap-4"}>
        {#if turn.speaker !== null}
          <div class="pt-1 leading-tight">
            <div class="font-mono text-[12px] text-ink-muted">Спикер {turn.speaker + 1}</div>
            <div class="mt-0.5 font-mono text-[12px] tabular-nums text-ink-muted">{clock(turn.start)}</div>
          </div>
        {/if}
        <div class="max-w-[68ch] whitespace-pre-wrap text-[15px] leading-7 text-ink">
          {#each turn.parts as part, at (at)}
            {#if part.entity}
              <mark
                class={chipClass(part.entity.type)}
                title={`${part.entity.label}, ${part.entity.token}, ${Math.round(part.entity.score * 100)}%`}
              >{part.text}</mark>
            {:else if part.hit !== undefined}
              <mark data-hit={part.hit} class={part.hit === cursor ? "hit hit-current" : "hit"}>{part.text}</mark>
            {:else}
              <span>{part.text}</span>
            {/if}
          {/each}
        </div>
      </li>
    {/each}
  </ul>
</div>
