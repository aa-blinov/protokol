import type { Entity } from "../api";

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

export interface Piece {
  text: string;
  entity?: Entity;
  /** Index into the whole transcript's hit list, so the current one can be told apart. */
  hit?: number;
}

const KNOWN_TYPES = new Set([
  "PERSON",
  "ADDRESS",
  "PHONE",
  "EMAIL",
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
  "URL",
  "IP",
  "OTHER",
]);

export const chipClass = (type: string) =>
  `chip ${KNOWN_TYPES.has(type) ? `chip-${type}` : "chip-OTHER"}`;

/** Stop counting past this. A query of "а" hits a long transcript tens of
 *  thousands of times, and nobody scrolls through that -- but rendering every
 *  one of them would cost more than the search is worth. */
export const MAX_HITS = 2000;

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

/** Cuts `text` at every boundary any span introduces and labels each run.
 *
 *  Entities and search hits overlap -- a person can be found by name *and* be
 *  marked as personal data -- so painting one over the other would either hide
 *  a match or drop a chip. Walking the sorted boundaries once instead keeps
 *  both correct without either having to win. */
export function split(text: string, entities: Entity[], hits: Hit[]): Piece[] {
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

/** The entity spans that fall inside one turn, shifted to that turn's own text. */
export function within(entities: Entity[], offset: number, length: number): Entity[] {
  const end = offset + length;
  return entities
    .filter((entity) => entity.start >= offset && entity.end <= end)
    .map((entity) => ({ ...entity, start: entity.start - offset, end: entity.end - offset }));
}

/** A clock for a speaker turn: 0:00, 1:07, 12:34. */
export function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
