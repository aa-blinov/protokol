/** Renders text with entity spans highlighted as placeholder chips. */

import type { Entity } from "./api";

const KNOWN_TYPES = new Set([
  "PERSON",
  "ADDRESS",
  "PHONE",
  "EMAIL",
  "URL",
  "IP",
  "PASSPORT",
  "INN",
  "SNILS",
  "OMS",
  "CARD",
  "DRIVER_LICENSE",
  "MILITARY_ID",
  "BIRTH_CERTIFICATE",
  "OGRNIP",
  "SECRET",
]);

export const chipClass = (type: string) => `chip ${KNOWN_TYPES.has(type) ? `chip-${type}` : "chip-OTHER"}`;

/** A search match: character offsets into the text being rendered.
 *
 *  `index` is the match's position in the *whole* transcript's hit list, which
 *  is not the same as its position in a per-speaker-turn slice. The transcript
 *  sets it so "which match is current" stays answerable when the text is cut
 *  into turns; without it, the second turn would report matches 1, 2, 3 and
 *  never light up. */
export interface Hit {
  start: number;
  end: number;
  index?: number;
}

/** Stop counting past this. A query of "а" hits a long transcript tens of
 *  thousands of times, and nobody scrolls through that -- but rendering every
 *  one of them as a highlighted span would freeze the tab. */
export const MAX_HITS = 2000;

/** Every occurrence of `query` in `text`, case-insensitively.
 *
 *  Both sides are lower-cased rather than using a regular expression, so a
 *  query full of `(`, `[` or `\` -- a Russian text full of quotes and dashes --
 *  cannot throw. Overlapping matches are not returned: searching "аа" in
 *  "ааа" gives one hit, not two fighting over the same characters. */
export function findHits(text: string, query: string): Hit[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const haystack = text.toLowerCase();
  const hits: Hit[] = [];
  let at = haystack.indexOf(needle);
  while (at !== -1 && hits.length < MAX_HITS) {
    hits.push({ start: at, end: at + needle.length });
    at = haystack.indexOf(needle, at + needle.length);
  }
  return hits;
}

interface Piece {
  text: string;
  entity?: Entity;
  /** Index into the whole transcript's hit list, so the current one can be told apart. */
  hit?: number;
}

/** Cuts `text` at every boundary any span introduces and labels each run.
 *
 *  Entities and search hits overlap -- a person can be found by name *and* be
 *  marked as personal data -- so painting one over the other would either hide
 *  a match or drop a chip. Walking the sorted boundaries once instead keeps
 *  both correct without either having to win.
 */
function split(text: string, entities: Entity[], hits: Hit[]): Piece[] {
  if (!entities.length && !hits.length) return [{ text }];
  const bounds = new Set<number>([0, text.length]);
  for (const entity of entities) {
    if (entity.start >= 0 && entity.end <= text.length) {
      bounds.add(entity.start);
      bounds.add(entity.end);
    }
  }
  for (const hit of hits) {
    if (hit.start >= 0 && hit.end <= text.length) {
      bounds.add(hit.start);
      bounds.add(hit.end);
    }
  }
  const points = [...bounds].sort((a, b) => a - b);
  const pieces: Piece[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (end <= start) continue;
    const entity = entities.find((item) => item.start <= start && end <= item.end);
    const containing = hits.find((item) => item.start <= start && end <= item.end);
    pieces.push({
      text: text.slice(start, end),
      entity,
      hit: containing ? (containing.index ?? hits.indexOf(containing)) : undefined,
    });
  }
  return pieces;
}

/** Text with personal-data chips, and with the current search match outlined. */
export function Highlighted({
  text,
  entities,
  hits = [],
  current = null,
}: {
  text: string;
  entities: Entity[];
  hits?: Hit[];
  current?: number | null;
}) {
  const pieces = split(text, entities, hits);
  return (
    <p className="whitespace-pre-wrap leading-7 text-stone-800">
      {pieces.map((piece, index) => {
        if (piece.entity) {
          return (
            <mark
              key={index}
              className={chipClass(piece.entity.type)}
              title={`${piece.entity.label}, ${piece.entity.token}, ${Math.round(piece.entity.score * 100)}%`}
            >
              {piece.text}
            </mark>
          );
        }
        if (piece.hit !== undefined) {
          return (
            <mark
              key={index}
              data-hit={piece.hit}
              className={piece.hit === current ? "hit hit-current" : "hit"}
            >
              {piece.text}
            </mark>
          );
        }
        return <span key={index}>{piece.text}</span>;
      })}
    </p>
  );
}

/** Renders already-masked text, turning [TOKEN] into chips. */
export function MaskedView({ text, entityMap }: { text: string; entityMap: Record<string, string> }) {
  // A token may carry a case tag the model added: [PERSON_1|gen]. The chip shows the token alone.
  const parts = text.split(/(\[[A-Z_]+_\d+(?:\|[a-z]+)?\])/g);
  return (
    <p className="whitespace-pre-wrap leading-7 text-stone-800">
      {parts.map((part, index) => {
        const match = part.match(/^\[([A-Z_]+_\d+)(?:\|[a-z]+)?\]$/);
        if (!match) return <span key={index}>{part}</span>;
        const token = match[1];
        const type = token.replace(/_\d+$/, "");
        return (
          <mark key={index} className={chipClass(type)} title={`${token} → ${entityMap[token] ?? ""}`}>
            {token}
          </mark>
        );
      })}
    </p>
  );
}
