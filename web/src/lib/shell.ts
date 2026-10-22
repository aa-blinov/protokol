/** The shell's own helpers: the text export, the report it writes, and the
 *  small formatting the previous implementation kept next to them.
 *
 *  They live apart from the shell because they are pure: the shell owns the
 *  state, these own the text. */

import type { AnalysisResult, Session } from "../api";
import { humanDuration } from "./format";

export const PRODUCT_NAME = "Протокол";

/** The transcript as copyable text: speaker turns when diarized, else plain. */
export function transcriptText(analysis: AnalysisResult): string {
  if (analysis.segments.length === 0) return analysis.transcript;
  return analysis.segments
    .map((segment) => `Спикер ${segment.speaker + 1}: ${segment.text}`)
    .join("\n");
}

/** The file behind «Скачать .txt»: the whole document, as text.
 *
 *  Blocks are joined by a blank line and the empties are collapsed: filtering
 *  out the nulls alone left a run of blank lines wherever a section was
 *  missing, which is most of a document without a summary. */
export function buildReport(session: Session, labels: Record<string, string>): string {
  const { analysis, summaries } = session;
  const made = Object.entries(summaries);
  const blocks = [
    [
      `${PRODUCT_NAME}: расшифровка встречи`,
      `Файл: ${session.name}`,
      `Дата: ${new Date(session.createdAt).toLocaleString("ru-RU")}`,
      `Длительность: ${humanDuration(analysis.duration_sec)}`,
      ...(made.length
        ? [`Модель: ${[...new Set(made.map(([, s]) => s.llm_model))].join(", ")}`]
        : []),
    ],
    // Every summary, each under its own mode. Picking one would leave the rest
    // out of the file, and this file is the artefact that goes to someone else.
    ...made.map(([mode, s]) => [`ВЫЖИМКА: ${labels[mode] ?? mode}`, s.reply_unmasked]),
    ["РАСШИФРОВКА", transcriptText(analysis)],
    // The substitution table, not the masked text itself: the table is what a
    // reader can check by hand, and the masked copy is the same length as the
    // transcript above it for no added information.
    ...(Object.keys(analysis.entity_map).length
      ? [
          [
            "ЧТО СКРЫТО",
            ...Object.entries(analysis.entity_map).map(([token, value]) => `${token} → ${value}`),
          ],
        ]
      : []),
  ];
  return blocks.map((block) => block.join("\n").trim()).join("\n\n").trim() + "\n";
}

/** Hands a text file to the browser. */
export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** "12 с", "1 мин 10 с" -- short enough for a progress line. */
export function humanSeconds(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} с`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m < 60) return s ? `${m} мин ${s} с` : `${m} мин`;
  return `${Math.floor(m / 60)} ч ${m % 60} мин`;
}

/** One run of the masked text: plain words, or a placeholder to chip. */
export interface MaskedPiece {
  text: string;
  /** The placeholder without the brackets, when this run is one. */
  token?: string;
  /** The kind of the placeholder, for the chip's colour. */
  type?: string;
}

/** Cuts the masked text into words and [PERSON_1] placeholders.
 *
 *  A token may carry a case tag the model added: [PERSON_1|gen]. The chip
 *  shows the token alone. */
export function maskedPieces(text: string): MaskedPiece[] {
  const pieces: MaskedPiece[] = [];
  for (const part of text.split(/(\[[A-Z_]+_\d+(?:\|[a-z]+)?\])/g)) {
    if (!part) continue;
    const match = /^\[([A-Z_]+_\d+)(?:\|[a-z]+)?\]$/.exec(part);
    if (!match) {
      pieces.push({ text: part });
      continue;
    }
    const token = match[1];
    pieces.push({ text: part, token, type: token.replace(/_\d+$/, "") });
  }
  return pieces;
}
