/** Typed client for the FastAPI backend. */

export interface Entity {
  token: string;
  type: string;
  label: string;
  start: number;
  end: number;
  text: string;
  score: number;
}

export interface MaskResponse {
  masked_text: string;
  entity_map: Record<string, string>;
  entities: Entity[];
}

export interface ProcessResult {
  transcript: string;
  masked_text: string;
  entity_map: Record<string, string>;
  entities: Entity[];
  llm_model: string;
  reply: string;
  reply_unmasked: string;
  duration_sec: number;
  timings: Record<string, number>;
}

export interface ProgressEvent {
  stage: "transcribe" | "mask" | "llm" | "done" | "error";
  pct: number;
  message: string;
  result?: ProcessResult;
}

export interface Session {
  id: string;
  name: string;
  createdAt: string;
  result: ProcessResult;
}

const jsonHeaders = { "Content-Type": "application/json" };

async function toError(response: Response): Promise<never> {
  let detail = `${response.status}`;
  try {
    const body = await response.json();
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    /* keep status only */
  }
  throw new Error(detail);
}

export async function maskText(text: string): Promise<MaskResponse> {
  const response = await fetch("/api/mask", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ text }),
  });
  if (!response.ok) await toError(response);
  return response.json();
}

export async function transcribe(file: File): Promise<{ text: string; duration_sec: number }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/transcribe", { method: "POST", body: form });
  if (!response.ok) await toError(response);
  return response.json();
}

/** Runs the full pipeline, reporting stage progress until the final result. */
export async function processAudio(
  file: File,
  llmModel: string,
  onProgress: (event: ProgressEvent) => void,
): Promise<ProcessResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("llm_model", llmModel);

  const response = await fetch("/api/process", { method: "POST", body: form });
  if (!response.ok) await toError(response);
  if (!response.body) throw new Error("Сервер не вернул поток ответа");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ProcessResult | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // NDJSON: one JSON object per line.
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) {
        const event = JSON.parse(line) as ProgressEvent;
        onProgress(event);
        if (event.stage === "error") throw new Error(event.message || "Ошибка обработки");
        if (event.result) result = event.result;
      }
      newline = buffer.indexOf("\n");
    }
  }

  if (!result) throw new Error("Сервер не вернул результат");
  return result;
}
