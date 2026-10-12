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

export interface SpeakerSegment {
  speaker: number;
  start: number;
  end: number;
  text: string;
  offset: number;
}

/** The single-pass shape, kept only to read history written before the split. */
export interface ProcessResult {
  transcript: string;
  masked_text: string;
  entity_map: Record<string, string>;
  entities: Entity[];
  llm_model: string;
  reply: string;
  reply_unmasked: string;
  duration_sec: number;
  segments: SpeakerSegment[];
  timings: Record<string, number>;
}

/** Audio turned into text, speakers and masks -- but no summary yet. */
export interface AnalysisResult {
  cache_key: string;
  transcript: string;
  masked_text: string;
  entity_map: Record<string, string>;
  entities: Entity[];
  segments: SpeakerSegment[];
  duration_sec: number;
  timings: Record<string, number>;
  /** True when the transcript came back from the previous run's cache. */
  cached: boolean;
}

export interface AnalysisProgress {
  stage: "transcribe" | "diarize" | "mask" | "done" | "error";
  pct: number;
  message: string;
  result?: AnalysisResult;
}

export interface SummarizeResult {
  reply: string;
  reply_unmasked: string;
  llm_model: string;
  /** Which focus produced this summary; null before the first one runs. */
  preset: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  /** What it actually cost. Null when the provider quotes no fixed price. */
  cost: { input: number | null; output: number | null; total: number | null };
  timings: Record<string, number>;
}

/** What one summary will roughly cost, before it is sent. */
export interface EstimateResult {
  tokens_in: number;
  tokens_out: number;
  /** More than one when the transcript is long enough to be split first. */
  requests: number;
  input: number | null;
  output: number | null;
  total: number | null;
  currency: string;
}

/** A recording in the history: the analysis, plus a summary once one exists. */
export interface Session {
  id: string;
  name: string;
  createdAt: string;
  analysis: AnalysisResult;
  summary: SummarizeResult | null;
}

const jsonHeaders = { "Content-Type": "application/json" };

/** Wraps fetch so a dropped connection reads as a sentence, not as a browser string.
 *
 *  `fetch` rejects with a bare `TypeError: Failed to fetch` when the sidecar is
 *  gone, and that string reached the toast verbatim. The person restarting the
 *  app needs to be told that, not shown the inside of Chromium's error. */
async function request(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await request(input, init);
  } catch {
    throw new Error(
      "Связь с внутренним сервисом прервалась. Закройте и снова откройте приложение, затем повторите.",
    );
  }
}

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

/** Reads an NDJSON stream, handing each line to `onEvent`.
 *
 *  Shared by /api/process and /api/analyse: both speak one JSON object per
 *  line, and the difference between them is which field carries the result --
 *  not how the bytes arrive. */
async function readStream<T>(
  response: Response,
  onEvent: (event: T) => void,
  isError: (event: T) => boolean,
  messageOf: (event: T) => string,
): Promise<void> {
  if (!response.body) throw new Error("Сервер не вернул поток ответа");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) {
        const event = JSON.parse(line) as T;
        onEvent(event);
        if (isError(event)) throw new Error(messageOf(event) || "Ошибка обработки");
      }
      newline = buffer.indexOf("\n");
    }
  }
}

/** Transcription, speaker split and masking -- everything but the summary.
 *
 *  No money is spent here and no text leaves the machine: the response carries
 *  the masked text that *would* be sent, so the user can read it before
 *  deciding whether to send anything. */
export async function analyseAudio(
  file: File,
  onProgress: (event: AnalysisProgress) => void,
): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await request("/api/analyse", { method: "POST", body: form });
  if (!response.ok) await toError(response);

  let result: AnalysisResult | null = null;
  await readStream<AnalysisProgress>(
    response,
    (event) => {
      onProgress(event);
      if (event.result) result = event.result;
    },
    (event) => event.stage === "error",
    (event) => event.message,
  );
  if (!result) throw new Error("Сервер не вернул результат");
  return result;
}

/** The summary alone, over a recording that has already been analysed.
 *
 *  Takes a cache key rather than audio: changing the focus re-runs this call
 *  without the recording ever being decoded a second time. */
export async function summarize(
  cacheKey: string,
  model: string,
  preset: string,
  extra?: string | null,
  maskedText?: string,
): Promise<SummarizeResult> {
  const response = await request("/api/summarize", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      cache_key: cacheKey,
      model,
      preset,
      extra: extra ?? null,
      // Sent alongside the key because the analysis cache holds only eight
      // recordings: without this, re-summarising anything from the history
      // works for a while and then fails with "загрузите заново".
      masked_text: maskedText ?? "",
    }),
  });
  if (!response.ok) await toError(response);
  return response.json();
}

/** What one summary over `chars` characters will roughly cost. */
export async function estimateCost(chars: number, model: string): Promise<EstimateResult> {
  const response = await request("/api/estimate", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ chars, model }),
  });
  if (!response.ok) await toError(response);
  return response.json();
}

/* ------------------------------------------------------------------ settings */

export interface SettingsState {
  has_key: boolean;
  /** Masked prefix/suffix; the key itself never reaches the browser. */
  key_hint: string;
  model: string;
  base_url: string;
  key_page: string;
  models_page: string;
  /** What to pull out of the recording. */
  preset: string;
  /** Extra requirement appended to the prompt; "" when none. */
  extra: string;
  presets: { key: string; label: string }[];
}

export interface SettingsResult {
  ok: boolean;
  detail: string;
  settings: SettingsState;
}

export interface KeyCheckResult {
  ok: boolean;
  detail: string;
  settings: SettingsState | null;
}

export interface ModelInfo {
  id: string;
  name: string;
  context: number | null;
  /** USD per million tokens; null when OpenRouter quotes no fixed price. */
  prompt_price: number | null;
  completion_price: number | null;
}

export async function getSettings(): Promise<SettingsState> {
  const response = await request("/api/settings");
  if (!response.ok) await toError(response);
  return response.json();
}

/** Checks a key against the given address without storing it. */
export async function verifyKey(key: string, baseUrl: string, remember: boolean): Promise<KeyCheckResult> {
  const response = await request("/api/settings/verify", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ key, base_url: baseUrl, remember }),
  });
  if (!response.ok) await toError(response);
  return response.json();
}

/** Saves the address, key and model. Empty values keep what is stored. */
export async function saveSettings(
  key: string,
  model: string,
  baseUrl: string,
  preset: string,
  extra: string,
): Promise<SettingsResult> {
  const response = await request("/api/settings", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ key, model, base_url: baseUrl, preset, extra }),
  });
  if (!response.ok) await toError(response);
  return response.json();
}

export async function getModels(): Promise<ModelInfo[]> {
  const response = await request("/api/models");
  if (!response.ok) await toError(response);
  return response.json();
}

/* ------------------------------------------------------------------- history */

/** Recordings kept by the sidecar in a file next to the settings.
 *
 *  Not localStorage: the desktop shell takes a random free port on every launch
 *  and Chromium scopes localStorage to the origin including the port, so the
 *  history was empty again after each restart. */
export async function getSessions(): Promise<Session[]> {
  const response = await request("/api/sessions");
  if (!response.ok) await toError(response);
  const stored = (await response.json()) as unknown[];
  return stored.map(toSession).filter((session): session is Session => session !== null);
}

export async function saveSessions(sessions: Session[]): Promise<void> {
  const response = await request("/api/sessions", {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(sessions.slice(0, 50)),
  });
  if (!response.ok) await toError(response);
}

/** Reads one stored entry, in the current shape or in the old one.
 *
 *  History written before the pipeline was split stores everything under
 *  `result`; those recordings are kept working rather than dropped. Their
 *  `cache_key` is empty, which is honest: the transcript they came from is no
 *  longer in the analysis cache, so re-running a summary on one would need the
 *  file again. The UI checks for that instead of pretending otherwise. */
function toSession(stored: unknown): Session | null {
  const entry = stored as Partial<Session> & { result?: ProcessResult };
  if (!entry || typeof entry !== "object") return null;
  if (entry.analysis && typeof entry.analysis === "object") {
    return {
      id: entry.id ?? "",
      name: entry.name ?? "Без названия",
      createdAt: entry.createdAt ?? new Date(0).toISOString(),
      analysis: entry.analysis,
      summary: entry.summary ?? null,
    };
  }
  const legacy = entry.result;
  if (!legacy || typeof legacy.transcript !== "string") return null;
  return {
    id: entry.id ?? "",
    name: entry.name ?? "Без названия",
    createdAt: entry.createdAt ?? new Date(0).toISOString(),
    analysis: {
      cache_key: "",
      transcript: legacy.transcript,
      masked_text: legacy.masked_text ?? "",
      entity_map: legacy.entity_map ?? {},
      entities: legacy.entities ?? [],
      segments: legacy.segments ?? [],
      duration_sec: legacy.duration_sec ?? 0,
      timings: legacy.timings ?? {},
      cached: false,
    },
    summary: legacy.reply
      ? {
          reply: legacy.reply,
          reply_unmasked: legacy.reply_unmasked ?? legacy.reply,
          llm_model: legacy.llm_model ?? "",
          preset: null,
          tokens_in: null,
          tokens_out: null,
          cost: { input: null, output: null, total: null },
          timings: {},
        }
      : null,
  };
}
