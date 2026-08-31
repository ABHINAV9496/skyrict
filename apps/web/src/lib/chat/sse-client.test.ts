import { beforeEach, describe, expect, it, vi } from "vitest";

import { parseSseFrame, splitSseFrames, streamAgentChat } from "@/lib/chat/sse-client";

const httpMocks = vi.hoisted(() => ({
  fetchWithSession: vi.fn(),
}));

vi.mock("@/lib/api/http", () => ({
  fetchWithSession: httpMocks.fetchWithSession,
  ApiError: class ApiError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

function sseResponse(chunks: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(new TextEncoder().encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

describe("splitSseFrames", () => {
  it("splits complete frames and keeps the partial tail", () => {
    const { frames, remainder } = splitSseFrames(
      "event: token\ndata: {\"delta\":\"A\"}\n\nevent: token\ndata: {\"delta\":\"B\"}\n\n",
    );
    expect(frames).toHaveLength(2);
    expect(remainder).toBe("");
  });

  it("keeps an incomplete frame in the remainder for the next chunk", () => {
    const { frames, remainder } = splitSseFrames("event: token\ndata: {\"delt");
    expect(frames).toEqual([]);
    expect(remainder).toBe("event: token\ndata: {\"delt");
  });
});

describe("parseSseFrame", () => {
  it("parses a classification event", () => {
    expect(
      parseSseFrame(
        'event: classification\ndata: {"agents":["inventory_monitor"],"confidence":0.9,"abstain":false,"reason":null}\n\n',
      ),
    ).toEqual({
      type: "classification",
      agents: ["inventory_monitor"],
      confidence: 0.9,
      abstain: false,
      reason: null,
    });
  });

  it("parses agent_start, token, citations, done and error events", () => {
    expect(parseSseFrame('event: agent_start\ndata: {"agent":"inventory_monitor","display_name":"Inventory Monitor"}\n\n')).toEqual({
      type: "agent_start",
      agent: "inventory_monitor",
      display_name: "Inventory Monitor",
    });

    expect(parseSseFrame('event: token\ndata: {"agent":"inventory_monitor","delta":"Hello"}\n\n')).toEqual({
      type: "token",
      agent: "inventory_monitor",
      delta: "Hello",
    });

    expect(
      parseSseFrame(
        'event: citations\ndata: {"agent":"inventory_monitor","citations":[{"source_ref":"docs/i.md","module":"inventory","title":"Inventory docs","url":"/d/docs/i.md"}]}\n\n',
      ),
    ).toEqual({
      type: "citations",
      agent: "inventory_monitor",
      citations: [
        {
          source_ref: "docs/i.md",
          module: "inventory",
          title: "Inventory docs",
          url: "/d/docs/i.md",
        },
      ],
    });

    expect(parseSseFrame('event: done\ndata: {"agents":["hr_copilot"]}\n\n')).toEqual({
      type: "done",
      agents: ["hr_copilot"],
    });

    expect(parseSseFrame('event: error\ndata: {"message":"ai_unavailable"}\n\n')).toEqual({
      type: "error",
      message: "ai_unavailable",
    });
  });

  it("skips unknown events and malformed frames", () => {
    expect(parseSseFrame('event: mystery\ndata: {"x":1}\n\n')).toBeNull();
    expect(parseSseFrame("event: token\ndata: not-json\n\n")).toBeNull();
    expect(parseSseFrame("")).toBeNull();
  });
});

describe("streamAgentChat", () => {
  beforeEach(() => {
    httpMocks.fetchWithSession.mockReset();
  });

  it("posts the message and dispatches events as frames arrive", async () => {
    httpMocks.fetchWithSession.mockResolvedValue(
      sseResponse([
        'event: classification\ndata: {"agents":["inventory_monitor"],"confidence":0.9,"abstain":false,"reason":null}\n\n',
        'event: token\ndata: {"agent":"inventory_monitor","delta":"Aggregating"}\n\n',
        'event: token\ndata: {"agent":"inventory_monitor","delta":" stock"}\n\n',
        'event: done\ndata: {"agents":["inventory_monitor"]}\n\n',
      ]),
    );

    const seen: string[] = [];
    await streamAgentChat({
      message: "Stock levels?",
      onEvent: (event) => seen.push(event.type),
    });

    expect(httpMocks.fetchWithSession).toHaveBeenCalledWith(
      "/api/v1/ai/agents/chat/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "Stock levels?" }),
      }),
    );
    expect(seen).toEqual(["classification", "token", "token", "done"]);
  });

  it("parses frames that span multiple chunks", async () => {
    httpMocks.fetchWithSession.mockResolvedValue(
      sseResponse([
        'event: classification\ndata: {"agents":["inventory_mon',
        'itor"],"confidence":0.9,"abstain":false,"reason":null}\n\n',
        'event: token\ndata: {"agent":"inventory_monitor","de',
        'lta":"ok"}\n\nevent: done\ndata: {"agents":["inventory_monitor"]}\n\n',
      ]),
    );

    const seen: string[] = [];
    await streamAgentChat({
      message: "hi",
      onEvent: (event) => seen.push(event.type),
    });

    expect(seen).toEqual(["classification", "token", "done"]);
  });

  it("dispatches an error event frame without throwing", async () => {
    httpMocks.fetchWithSession.mockResolvedValue(
      sseResponse(['event: error\ndata: {"message":"ai_unavailable"}\n\n']),
    );

    const seen: string[] = [];
    await streamAgentChat({
      message: "hi",
      onEvent: (event) => seen.push(event.type),
    });

    expect(seen).toEqual(["error"]);
  });

  it("rejects with ApiError status when the BFF answers an error status", async () => {
    httpMocks.fetchWithSession.mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "Core service is unavailable. Please try again." }),
        { status: 502, headers: { "content-type": "application/json" } },
      ),
    );

    await expect(
      streamAgentChat({ message: "hi", onEvent: () => undefined }),
    ).rejects.toMatchObject({ status: 502, message: "Core service is unavailable. Please try again." });
  });
});