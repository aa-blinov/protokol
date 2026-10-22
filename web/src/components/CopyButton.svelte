<script lang="ts">
  /** A quiet text button that copies and says so for a moment. */
  import { onDestroy } from "svelte";
  import { Button } from "@monos/ui";

  export let text = "";
  export let label = "Скопировать";

  let copied = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        copied = false;
      }, 1500);
    } catch {
      /* The clipboard is not ours to insist on: a denied permission leaves the
         word as it was rather than claiming it was copied. */
    }
  }

  onDestroy(() => {
    if (timer) clearTimeout(timer);
  });
</script>

<Button variant="quiet" size="sm" on:click={copy}>{copied ? "Скопировано" : label}</Button>
