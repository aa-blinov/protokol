<script lang="ts">
  /** The model's answer, rendered as the document's own typography.
   *
   *  The model answers in Markdown, so the renderer covers the constructs a
   *  protocol actually uses: headings, bullet and numbered lists, tables, code,
   *  quotes, rules, and inline emphasis/link/code. Hand-rolled to keep the app
   *  dependency-free and to keep control of the document's own typography.
   *
   *  The inline rules live in one place and are handed to the page as markup;
   *  the text in them is escaped here, so nothing the model wrote can become a
   *  tag of its own. */
  export let text = "";

  /** One inline span of a line. */
  type Part =
    | { kind: "text"; text: string }
    | { kind: "code"; text: string }
    | { kind: "strong"; text: string }
    | { kind: "em"; text: string }
    | { kind: "del"; text: string }
    | { kind: "link"; text: string; href: string };

  /** One block of the document. */
  type Block =
    | { kind: "paragraph"; parts: Part[] }
    | { kind: "heading"; parts: Part[] }
    | { kind: "quote"; parts: Part[] }
    | { kind: "code"; code: string }
    | { kind: "rule" }
    | { kind: "list"; ordered: boolean; items: Part[][] }
    | { kind: "table"; head: Part[][]; rows: Part[][][] };

  const TEXT = "text-[15px] leading-7 text-ink";
  const CODE = "rounded-ui bg-surface px-1 py-0.5 font-mono text-[0.85em] text-ink-soft";
  const STRONG = "font-semibold text-ink";
  const LINK = "text-accent-text underline decoration-line underline-offset-2";

  const INLINE =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(_[^_\n]+_)|(~~[^~]+~~)|(\[[^\]]+\]\([^)\s]+\))/g;

  $: blocks = parse(text);

  /** The blocks of the document, in the order they are read. */
  function parse(text: string): Block[] {
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    const blocks: Block[] = [];
    const paragraph: string[] = [];
    let i = 0;

    const flushParagraph = () => {
      if (paragraph.length === 0) return;
      blocks.push({ kind: "paragraph", parts: parseInline(paragraph.join(" ")) });
      paragraph.length = 0;
    };

    const takeWhile = (test: RegExp, items: string[]) => {
      while (i < lines.length) {
        const match = test.exec(lines[i].trim());
        if (!match) break;
        items.push(match[1]);
        i++;
      }
    };

    while (i < lines.length) {
      const raw = lines[i];
      const line = raw.trim();

      if (line === "") {
        flushParagraph();
        i++;
        continue;
      }

      if (/^```/.test(line)) {
        flushParagraph();
        const code: string[] = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i].trim())) {
          code.push(lines[i]);
          i++;
        }
        i++;
        blocks.push({ kind: "code", code: code.join("\n") });
        continue;
      }

      if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        flushParagraph();
        const header = parseRow(line);
        const rows: string[][] = [];
        i += 2;
        while (i < lines.length && lines[i].trim().includes("|") && lines[i].trim() !== "") {
          rows.push(parseRow(lines[i]));
          i++;
        }
        blocks.push({
          kind: "table",
          head: header.map(parseInline),
          rows: rows.map((row) => row.map(parseInline)),
        });
        continue;
      }

      const heading = /^(#{1,6})\s+(.*)$/.exec(line) ?? /^\*\*(.+?)\*\*:?$/.exec(line);
      if (heading) {
        flushParagraph();
        blocks.push({ kind: "heading", parts: parseInline(heading[2] ?? heading[1]) });
        i++;
        continue;
      }

      if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) {
        flushParagraph();
        blocks.push({ kind: "rule" });
        i++;
        continue;
      }

      if (/^>\s?/.test(line)) {
        flushParagraph();
        const quote: string[] = [];
        while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
          quote.push(lines[i].trim().replace(/^>\s?/, ""));
          i++;
        }
        blocks.push({ kind: "quote", parts: parseInline(quote.join(" ")) });
        continue;
      }

      const ordered = /^\d+[.)]\s+(.*)$/.exec(line);
      if (ordered) {
        flushParagraph();
        const items = [ordered[1]];
        i++;
        takeWhile(/^\d+[.)]\s+(.*)$/, items);
        blocks.push({ kind: "list", ordered: true, items: items.map(parseInline) });
        continue;
      }

      const bullet = /^[-*•+]\s+(.*)$/.exec(line);
      if (bullet) {
        flushParagraph();
        const items = [bullet[1]];
        i++;
        takeWhile(/^[-*•+]\s+(.*)$/, items);
        blocks.push({ kind: "list", ordered: false, items: items.map(parseInline) });
        continue;
      }

      paragraph.push(line);
      i++;
    }
    flushParagraph();
    return blocks;
  }

  /** The inline spans of one line: code, bold, italic, strikethrough, links. */
  function parseInline(line: string): Part[] {
    const parts: Part[] = [];
    let last = 0;
    for (const match of line.matchAll(INLINE)) {
      const at = match.index ?? 0;
      if (at > last) parts.push({ kind: "text", text: line.slice(last, at) });
      const token = match[0];
      if (token.startsWith("`")) {
        parts.push({ kind: "code", text: token.slice(1, -1) });
      } else if (token.startsWith("**") || token.startsWith("__")) {
        parts.push({ kind: "strong", text: token.slice(2, -2) });
      } else if (token.startsWith("~~")) {
        parts.push({ kind: "del", text: token.slice(2, -2) });
      } else if (token.startsWith("[")) {
        const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
        parts.push({
          kind: "link",
          text: link ? link[1] : token,
          href: link ? link[2] : "#",
        });
      } else {
        parts.push({ kind: "em", text: token.slice(1, -1) });
      }
      last = at + token.length;
    }
    if (last < line.length) parts.push({ kind: "text", text: line.slice(last) });
    return parts;
  }

  /** The inline spans as markup. The text is escaped here, so a model that
   *  writes a tag gets it printed rather than obeyed. */
  function inline(parts: Part[]): string {
    return parts
      .map((part) => {
        if (part.kind === "text") return escape(part.text);
        if (part.kind === "code") return `<code class="${CODE}">${escape(part.text)}</code>`;
        if (part.kind === "strong") return `<strong class="${STRONG}">${escape(part.text)}</strong>`;
        if (part.kind === "em") return `<em>${escape(part.text)}</em>`;
        if (part.kind === "del") return `<del>${escape(part.text)}</del>`;
        return `<a href="${escape(safeHref(part.href))}" target="_blank" rel="noreferrer" class="${LINK}">${escape(
          part.text,
        )}</a>`;
      })
      .join("");
  }

  /** A link the model wrote is not trusted: a scheme that can run script is
   *  dropped and the label stays on the page without a target. */
  function safeHref(href: string): string {
    const scheme = href.replace(/[\u0000-\u0020]/g, "").toLowerCase();
    if (/^(javascript|data|vbscript):/.test(scheme)) return "#";
    return href;
  }

  function escape(value: string): string {
    return value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function parseRow(line: string): string[] {
    let value = line.trim();
    if (value.startsWith("|")) value = value.slice(1);
    if (value.endsWith("|")) value = value.slice(0, -1);
    return value.split("|").map((cell) => cell.trim());
  }

  const isTableSeparator = (line: string): boolean =>
    line.includes("-") && /^\s*\|?[\s:|-]+\|?\s*$/.test(line) && !/[^\s:|-]/.test(line);
</script>

<div>
  {#each blocks as block, index (index)}
    {#if block.kind === "paragraph"}
      <p class="mt-2 max-w-[68ch] {TEXT}">{@html inline(block.parts)}</p>
    {:else if block.kind === "heading"}
      <h4 class="mt-5 font-semibold tracking-tight text-ink">{@html inline(block.parts)}</h4>
    {:else if block.kind === "quote"}
      <blockquote class="mt-2 max-w-[68ch] border-l border-line-strong pl-4 text-ink-soft">{@html inline(block.parts)}</blockquote>
    {:else if block.kind === "code"}
      <pre
        class="mt-2 max-w-[68ch] overflow-x-auto rounded-ui border border-line bg-surface p-3 font-mono text-[13px] leading-6 text-ink-soft"
      ><code>{block.code}</code></pre>
    {:else if block.kind === "rule"}
      <hr class="my-5 border-t border-line" />
    {:else if block.kind === "list"}
      {#if block.ordered}
        <ol class="ml-5 mt-2 list-decimal space-y-1 {TEXT}">
          {#each block.items as item, at (at)}
            <li>{@html inline(item)}</li>
          {/each}
        </ol>
      {:else}
        <ul class="ml-5 mt-2 list-disc space-y-1 {TEXT}">
          {#each block.items as item, at (at)}
            <li>{@html inline(item)}</li>
          {/each}
        </ul>
      {/if}
    {:else if block.kind === "table"}
      <div class="mt-3 max-w-[68ch] overflow-x-auto">
        <table class="w-full border-collapse {TEXT}">
          <thead>
            <tr>
              {#each block.head as cell, column (column)}
                <th class="border-b border-line px-2 py-1 text-left font-semibold text-ink">{@html inline(cell)}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each block.rows as row, at (at)}
              <tr>
                {#each row as cell, column (column)}
                  <td class="border-b border-line px-2 py-1 align-top">{@html inline(cell)}</td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/each}
</div>
