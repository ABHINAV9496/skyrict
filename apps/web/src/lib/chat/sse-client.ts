/**
 * Streaming SSE client for the supervisor chat (SKY-60).
 *
 * POSTs one turn to the web BFF `/api/v1/ai/agents/chat/stream` (which relays
 * the core monolith's `text/event-stream` chunk-by-chunk without buffering),
 * parses the SSE frames incrementally, and dispatches typed events to the
 * caller as they arrive — so the shell renders tokens live instead of waiting
 * for a whole answer.
 *
 * Event contract (matches ai-agent `api/v1/routers/chat.py`):
 *   classification → (per agent) agent_start → token* → citations → done
 *   error            replaces the stream of the failing turn
 */

import { ApiError, fetchWithSession } from "@/lib/api/http";

export interface ChatCitation {
  source_ref: string;
  module: string;
  title: string;
  url: string | null;
}

export type ChatStreamEvent =
  | {
      type: "classification";
      agents: string[];
      confidence: number;
      abstain: boolean;
      reason: string | null;
    }
  | { type: "agent_start"; agent: string; display_name: string }
  | { type: "token"; agent: string; delta: string }
  | { type: "citations"; agent: string; citations: ChatCitation[] }
  | { type: "done"; agents: string[] }
  | { type: "error"; message: string };

const EVENT_CLASSIFICATION = "classification";
const EVENT_AGENT_START = "agent_start";
const EVENT_TOKEN = "token";
const EVENT_CITATIONS = "citations";
const EVENT_DONE = "done";
const EVENT_ERROR = "error";

/**
 * Split an SSE byte buffer into complete frames, leaving the last partial
 * frame in `remainder` for the next chunk. Frames are separated by a blank
 * line (`\n\n`) per the SSE spec.
 */
export function splitSseFrames(buffer: string): { frames: string[]; remainder: string } {
  const frames: string[] = [];
  let rest = buffer;
  let index = rest.indexOf("\n\n");
  while (index !== -1) {
    frames.push(rest.slice(0, index));
    rest = rest.slice(index + 2);
    index = rest.indexOf("\n\n");
  }
  return { frames, remainder: rest };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function parseCitations(value: unknown): ChatCitation[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    const title = typeof record.title === "string" ? record.title : "";
    if (!title) return [];
    return [
      {
        source_ref: typeof record.source_ref === "string" ? record.source_ref : "",
        module: typeof record.module === "string" ? record.module : "",
        title,
        url: typeof record.url === "string" ? record.url : null,
      },
    ];
  });
}

/**
 * Parse one SSE frame into a typed chat event. Malformed or unknown event
 * names are skipped (forward compatibility with new supervisor events).
 */
export function parseSseFrame(frame: string): ChatStreamEvent | null {
  const text = frame.trim();
  if (!text) return null;

  let name = "";
  let data = "";
  for (const line of text.split("\n")) {
    if (line.startsWith("event:")) name = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) data += line.slice("data:".length).trim();
  }
  if (!name || !data) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;

  switch (name) {
    case EVENT_CLASSIFICATION:
      return {
        type: "classification",
        agents: stringList(record.agents),
        confidence: typeof record.confidence === "number" ? record.confidence : 0,
        abstain: Boolean(record.abstain),
        reason: typeof record.reason === "string" ? record.reason : null,
      };
    case EVENT_AGENT_START:
      return {
        type: "agent_start",
        agent: typeof record.agent === "string" ? record.agent : "",
        display_name: typeof record.display_name === "string" ? record.display_name : "",
      };
    case EVENT_TOKEN:
      return {
        type: "token",
        agent: typeof record.agent === "string" ? record.agent : "",
        delta: typeof record.delta === "string" ? record.delta : "",
      };
    case EVENT_CITATIONS:
      return {
        type: "citations",
        agent: typeof record.agent === "string" ? record.agent : "",
        citations: parseCitations(record.citations),
      };
    case EVENT_DONE:
      return { type: "done", agents: stringList(record.agents) };
    case EVENT_ERROR:
      return {
        type: "error",
        message: typeof record.message === "string" ? record.message : "The agent could not complete this turn.",
      };
    default:
      return null;
  }
}

/** Attachment sent with a chat message (base64-encoded content for the backend). */
export interface StreamAttachment {
  name: string;
  type: string;
  size: number;
  /** Base64-encoded file content (data-URL stripped — pure base64). */
  base64: string;
}

export interface StreamAgentChatInput {
  message: string;
  conversationId?: string;
  attachments?: StreamAttachment[];
  signal?: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
}

/**
 * Stream one supervisor turn. Resolves when the stream ends (server or
 * abort); rejects with `ApiError` when the BFF/backend answers with an error
 * status before any SSE frame (e.g. 502 service unavailable).
 */
export async function streamAgentChat(input: StreamAgentChatInput): Promise<void> {
  const payload: Record<string, unknown> = { message: input.message };
  if (input.conversationId) {
    payload.conversation_id = input.conversationId;
  }
  if (input.attachments && input.attachments.length > 0) {
    payload.attachments = input.attachments;
  }

  const response = await fetchWithSession("/api/v1/ai/agents/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: input.signal,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: { error?: { message?: string }; message?: string } | string;
    };
    let message = "The agent could not be reached. Please try again.";
    if (typeof payload.detail === "string" && payload.detail) message = payload.detail;
    else if (typeof payload.detail === "object" && payload.detail) {
      message = payload.detail.error?.message ?? payload.detail.message ?? message;
    }
    throw new ApiError(response.status, message);
  }
  if (!response.body) {
    throw new ApiError(502, "The agent stream is unavailable. Please try again.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEventTime = Date.now();
  const STREAM_TIMEOUT_MS = 60_000; // 60s without any SSE frame = stuck
  try {
    for (;;) {
      // Race between reading the next chunk and a timeout.
      const readPromise = reader.read();
      const timeoutPromise = new Promise<never>((_, reject) => {
        const id = setTimeout(
          () => reject(new ApiError(504, "The agent stream timed out. Please try again.")),
          STREAM_TIMEOUT_MS,
        );
        // Clean up timeout on abort.
        input.signal?.addEventListener(
          "abort",
          () => clearTimeout(id),
          { once: true },
        );
      });

      const result = await Promise.race([readPromise, timeoutPromise]);
      const { done, value } = result as { done: boolean; value: Uint8Array | undefined };
      if (done) break;
      lastEventTime = Date.now();
      buffer += decoder.decode(value, { stream: true });
      const { frames, remainder } = splitSseFrames(buffer);
      buffer = remainder;
      for (const frame of frames) {
        const event = parseSseFrame(frame);
        if (event) input.onEvent(event);
      }
    }
    // Flush any trailing frame without the final blank line.
    const final = parseSseFrame(buffer);
    if (final) input.onEvent(final);
  } finally {
    reader.releaseLock();
  }
}