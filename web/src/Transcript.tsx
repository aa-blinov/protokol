/** The transcript, with search that works on an hour-long recording.
 *
 *  A meeting transcript is several screens of scrolling and nobody re-reads it
 *  linearly -- people go back to it for one thing they half-remember being
 *  said. Search is over the original text, not the masked copy, because the
 *  person searching wants the words that were spoken; the personal-data chips
 *  stay visible underneath so it is still obvious what would be hidden. */

import { useEffect, useMemo, useRef, useState } from "react";
import { findHits, Highlighted, MAX_HITS, type Hit } from "./Highlight";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import type { AnalysisResult, Entity } from "./api";

const CAP = 4000;

export function Transcript({ analysis }: { analysis: AnalysisResult }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [full, setFull] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  const hits = useMemo(() => findHits(analysis.transcript, query), [analysis.transcript, query]);
  // Searching a transcript that is capped to its first screen would report hits
  // nobody can see, so the cap lifts itself the moment a query is typed.
  const expanded = full || query.trim().length > 0;
  const long = analysis.transcript.length > CAP;

  useEffect(() => setCursor(0), [query]);

  // Bring the current match into view. Selected by attribute rather than by a
  // ref, because a match can land inside a personal-data chip and then there is
  // no dedicated element to hang one on.
  useEffect(() => {
    if (!hits.length) return;
    const node = root.current?.querySelector(`[data-hit="${cursor}"]`);
    node?.scrollIntoView({ block: "center", behavior: "auto" });
  }, [cursor, hits.length, expanded]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || !hits.length) return;
      event.preventDefault();
      setCursor((index) => (index + (event.shiftKey ? -1 : 1) + hits.length) % hits.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hits.length]);

  const step = (direction: 1 | -1) => {
    setCursor((index) => (index + direction + hits.length) % hits.length);
  };

  return (
    <div>
      <div className="no-print mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") step(event.shiftKey ? -1 : 1);
              if (event.key === "Escape" && query) {
                event.stopPropagation();
                setQuery("");
              }
            }}
            placeholder="Поиск по расшифровке"
            aria-label="Поиск по расшифровке"
            className="focus-ring w-full rounded border border-slate-300 bg-white py-1.5 pl-8 pr-8 text-sm placeholder:text-slate-500"
          />
          {query ? (
            <button
              onClick={() => setQuery("")}
              aria-label="Очистить поиск"
              className="focus-ring absolute right-1 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded text-slate-500 hover:bg-slate-100"
            >
              <X aria-hidden className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>

        {query ? (
          <div className="flex items-center gap-1">
            <span className="tabular-nums text-xs text-slate-500">
              {hits.length ? `${cursor + 1} из ${hits.length}` : "не найдено"}
            </span>
            <button
              onClick={() => step(-1)}
              disabled={!hits.length}
              aria-label="Предыдущее совпадение"
              className="focus-ring grid h-8 w-8 place-items-center rounded border border-slate-300 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              <ChevronUp aria-hidden className="h-4 w-4" />
            </button>
            <button
              onClick={() => step(1)}
              disabled={!hits.length}
              aria-label="Следующее совпадение"
              className="focus-ring grid h-8 w-8 place-items-center rounded border border-slate-300 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              <ChevronDown aria-hidden className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {long && !expanded && !query ? (
          <button onClick={() => setFull(true)} className="focus-ring rounded text-xs text-blue-700 underline">
            Показать целиком
          </button>
        ) : null}
      </div>

      {hits.length >= MAX_HITS ? (
        <p className="mb-3 text-xs text-slate-500">
          Показаны первые {MAX_HITS} совпадений. Дополните запрос, чтобы сузить поиск.
        </p>
      ) : null}

      <div ref={root} className={long && !expanded ? "max-h-[30rem] overflow-y-auto pr-2" : undefined}>
        <Body analysis={analysis} hits={hits} cursor={cursor} />
      </div>
    </div>
  );
}

/** Speaker turns when diarization produced them, otherwise the plain text.
 *
 *  The two paths differ only in layout: hits are absolute offsets into the
 *  whole transcript and get shifted into each turn's own slice. */
function Body({ analysis, hits, cursor }: { analysis: AnalysisResult; hits: Hit[]; cursor: number }) {
  if (analysis.segments.length === 0) {
    return (
      <div className="max-w-[68ch] text-[15px] leading-7 text-slate-800">
        <Highlighted text={analysis.transcript} entities={analysis.entities} hits={hits} current={cursor} />
      </div>
    );
  }
  return (
    <ul className="space-y-5">
      {analysis.segments.map((segment, index) => {
        const from = segment.offset;
        const to = segment.offset + segment.text.length;
        // Absolute hits shifted into this turn's own slice, keeping each one's
        // place in the whole transcript so "current" stays meaningful.
        const inside = hits
          .map((hit, position) => ({ ...hit, index: position }))
          .filter((hit) => hit.start >= from && hit.end <= to)
          .map((hit) => ({ start: hit.start - from, end: hit.end - from, index: hit.index }));
        return (
          <li key={index} className="grid grid-cols-[92px_1fr] gap-4">
            <div className="pt-1 leading-tight">
              <div className="font-mono text-[12px] text-slate-500">Спикер {segment.speaker + 1}</div>
              <div className="mt-0.5 font-mono text-[12px] tabular-nums text-slate-500">
                {clock(segment.start)}
              </div>
            </div>
            <div className="max-w-[68ch] text-[15px] leading-7 text-slate-800">
              <Highlighted
                text={segment.text}
                entities={within(analysis.entities, from, segment.text.length)}
                hits={inside}
                current={cursor}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Entity spans that fall inside one turn, shifted to that turn's own text. */
function within(entities: Entity[], offset: number, length: number): Entity[] {
  const end = offset + length;
  return entities
    .filter((entity) => entity.start >= offset && entity.end <= end)
    .map((entity) => ({ ...entity, start: entity.start - offset, end: entity.end - offset }));
}

function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}