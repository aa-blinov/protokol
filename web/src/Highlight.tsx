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
]);

const chipClass = (type: string) => `chip ${KNOWN_TYPES.has(type) ? `chip-${type}` : "chip-OTHER"}`;

interface Piece {
  text: string;
  entity?: Entity;
}

function split(text: string, entities: Entity[]): Piece[] {
  const sorted = [...entities].sort((a, b) => a.start - b.start);
  const pieces: Piece[] = [];
  let cursor = 0;
  for (const entity of sorted) {
    if (entity.start < cursor) continue; // overlapping span: keep the first one
    if (entity.start > cursor) pieces.push({ text: text.slice(cursor, entity.start) });
    pieces.push({ text: text.slice(entity.start, entity.end), entity });
    cursor = entity.end;
  }
  if (cursor < text.length) pieces.push({ text: text.slice(cursor) });
  return pieces;
}

export function Highlighted({ text, entities }: { text: string; entities: Entity[] }) {
  if (!entities.length) return <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{text}</p>;
  return (
    <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">
      {split(text, entities).map((piece, index) =>
        piece.entity ? (
          <mark
            key={index}
            className={chipClass(piece.entity.type)}
            title={`${piece.entity.label} · ${piece.entity.token} · ${Math.round(piece.entity.score * 100)}%`}
          >
            {piece.text}
          </mark>
        ) : (
          <span key={index}>{piece.text}</span>
        ),
      )}
    </p>
  );
}

/** Renders already-masked text, turning [TOKEN] into chips. */
export function MaskedView({ text, entityMap }: { text: string; entityMap: Record<string, string> }) {
  const parts = text.split(/(\[[A-Z_]+_\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">
      {parts.map((part, index) => {
        const match = part.match(/^\[([A-Z_]+_\d+)\]$/);
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
