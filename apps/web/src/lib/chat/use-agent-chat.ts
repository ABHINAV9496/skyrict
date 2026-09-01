"use client";

/**
 * `useAgentChat` — one conversation's message list driven by the real SSE
 * supervisor stream (SKY-60).
 *
 * Sending a message appends the user bubble, opens an empty agent bubble, and
 * streams token deltas into it as they arrive. The active agent is tracked
 * from the `agent_start` event so the UI can label the answering module;
 * citations attach to the bubble once the `citations` event lands. Aborting
 * the previous turn (button/unmount) closes the fetch, which cascades through
 * the BFF and stops the upstream LLM stream.
 *
 * Lifecycle guarantees:
 *   - Every stream reaches a terminal state: completed, failed, or cancelled.
 *   - On abort (user cancel or new message), the empty agent bubble is removed.
 *   - On premature stream close (no done/error event), the agent bubble is
 *     marked failed so the typing indicator never gets stuck.
 *   - Multiple concurrent sends are safe: the old stream is aborted, the new
 *     one proceeds independently.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  streamAgentChat,
  type ChatCitation,
  type ChatStreamEvent,
} from "@/lib/chat/sse-client";

export interface AgentChatCitation {
  title: string;
  sourceRef: string;
  module: string;
  url: string | null;
}

export interface AgentChatMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  createdAt: string;
  /** Module agent that answered (from `agent_start`); null while classifying. */
  agentName?: string | null;
  citations?: AgentChatCitation[];
  /** True when the turn failed and `content` holds the error copy. */
  failed?: boolean;
}

export interface AgentChatState {
  messages: AgentChatMessage[];
  sending: boolean;
  activeAgent: string | null;
  /**
   * Send a user turn and stream the agent response.
   *
   * `echo` marks the auto-start resend of a message that is already held in
   * `initialMessages` (and already persisted to the store). For an echo we do
   * NOT re-append the user bubble nor re-persist it. Every other call (typed
   * message or a resend) appends the user bubble and persists it.
   */
  send: (content: string, echo?: boolean) => Promise<void>;
  stop: () => void;
}

function newId(): string {
  return `msg-${crypto.randomUUID()}`;
}

function toMessage(citation: ChatCitation): AgentChatCitation {
  return {
    title: citation.title,
    sourceRef: citation.source_ref,
    module: citation.module,
    url: citation.url,
  };
}

/**
 * Yield to the browser's microtask queue so React can flush pending state
 * updates.  This avoids a race where `streamAgentChat` throws (e.g. 401)
 * before the agent bubble from the preceding `setMessages` is committed —
 * the error handler's updater would then not find the bubble and leave it
 * stuck on the loading dots forever.
 */
function yieldToReact(): Promise<void> {
  return new Promise((resolve) => {
    queueMicrotask(resolve);
  });
}

export function useAgentChat(
  initialMessages: AgentChatMessage[],
  options?: {
    initialMessagesComplete?: boolean;
    /** Called when a turn completes with the agent's full response text. */
    onComplete?: (content: string) => void;
    /** Called when a user message is appended, so callers can persist it. */
    onUserMessage?: (content: string) => void;
  },
): AgentChatState {
  const [messages, setMessages] = useState<AgentChatMessage[]>(initialMessages);
  const [sending, setSending] = useState(false);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeStreamsRef = useRef(0);

  // Track the latest agent message content so onComplete can read it
  // outside of setMessages updaters (which see stale state).
  const lastAgentContentRef = useRef("");

  // Use a ref so the send callback always reads the latest value without
  // needing to recreate the callback on prop changes.
  const initialCompleteRef = useRef(options?.initialMessagesComplete ?? false);
  const onCompleteRef = useRef(options?.onComplete);
  onCompleteRef.current = options?.onComplete;
  const onUserMessageRef = useRef(options?.onUserMessage);
  onUserMessageRef.current = options?.onUserMessage;

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(async (content: string, echo?: boolean) => {
    const trimmed = content.trim();
    if (!trimmed) return;

    // Abort any in-flight stream before starting a new one. The old stream's
    // finally block will clean up its agent bubble.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    activeStreamsRef.current += 1;
    setSending(true);
    setActiveAgent(null);
    lastAgentContentRef.current = "";

    const now = new Date().toISOString();
    const userMessage: AgentChatMessage = {
      id: newId(),
      role: "user",
      content: trimmed,
      createdAt: now,
    };
    const agentMessage: AgentChatMessage = {
      id: newId(),
      role: "agent",
      content: "",
      createdAt: now,
      agentName: null,
      citations: [],
      failed: false,
    };

    // The auto-start echoes a message that is already persisted and already
    // present in initialMessages, so do not append (nor persist) it again.
    // Every other send — a typed message or a resend — appends the user bubble
    // and persists it. Using an explicit `echo` flag (rather than inferring
    // from refs) is correct even when a conversation loads ending in an agent
    // message and no auto-start ever runs.
    const shouldAppendUser = !(echo && initialCompleteRef.current);

    setMessages((previous) =>
      shouldAppendUser
        ? [...previous, userMessage, agentMessage]
        : [...previous, agentMessage],
    );

    // Persist the user message so it survives navigation away and back.
    if (shouldAppendUser) onUserMessageRef.current?.(trimmed);

    // Yield to the microtask queue so React commits the agent bubble to state
    // *before* we open the SSE stream.  Without this, a fast error (401, 502)
    // races the batch: the catch-block updater sees stale state and cannot
    // find the agent bubble — leaving it stuck on the loading dots forever.
    await yieldToReact();

    // Buffer token deltas and flush at animation-frame rate to avoid
    // re-rendering the entire message list (and re-parsing markdown) on
    // every single SSE token — the main cause of UI lag during streaming.
    let pendingDelta = "";
    let rafId = 0;

    const flushDelta = () => {
      rafId = 0;
      const batch = pendingDelta;
      pendingDelta = "";
      if (!batch) return;
      lastAgentContentRef.current += batch;
      setMessages((previous) =>
        previous.map((message) =>
          message.id === agentMessage.id
            ? { ...message, content: message.content + batch }
            : message,
        ),
      );
    };

    const appendDelta = (delta: string) => {
      pendingDelta += delta;
      if (rafId === 0) rafId = requestAnimationFrame(flushDelta);
    };

    // Track whether the stream reached a terminal state (done or error).
    // If the stream ends without either, we finalize the message in finally.
    let terminalReceived = false;

    const onEvent = (event: ChatStreamEvent) => {
      switch (event.type) {
        case "classification":
          if (!event.abstain) setActiveAgent(event.agents[0] ?? null);
          break;
        case "agent_start":
          setActiveAgent(event.agent);
          setMessages((previous) =>
            previous.map((message) =>
              message.id === agentMessage.id
                ? {
                    ...message,
                    agentName: event.display_name || event.agent,
                    citations: [],
                  }
                : message,
            ),
          );
          break;
        case "token":
          appendDelta(event.delta);
          break;
        case "citations":
          setMessages((previous) =>
            previous.map((message) =>
              message.id === agentMessage.id
                ? { ...message, citations: event.citations.map(toMessage) }
                : message,
            ),
          );
          break;
        case "done":
          terminalReceived = true;
          // Flush any remaining buffered tokens before signalling completion.
          if (rafId !== 0) {
            cancelAnimationFrame(rafId);
            rafId = 0;
            flushDelta();
          }
          setActiveAgent(null);
          // Persist the agent response to the conversation store so it
          // survives page navigation. Fire-and-forget — storage failure
          // is non-fatal.
          if (lastAgentContentRef.current) {
            onCompleteRef.current?.(lastAgentContentRef.current);
          }
          break;
        case "error":
          terminalReceived = true;
          // Cancel any pending animation frame so no stale flush runs after
          // the error replaces the message content.
          if (rafId !== 0) {
            cancelAnimationFrame(rafId);
            rafId = 0;
            pendingDelta = "";
          }
          lastAgentContentRef.current = event.message;
          setMessages((previous) =>
            previous.map((message) =>
              message.id === agentMessage.id
                ? {
                    ...message,
                    content:
                      event.message ||
                      "The agent could not complete this turn. Please try again.",
                    failed: true,
                  }
                : message,
            ),
          );
          setActiveAgent(null);
          break;
      }
    };

    try {
      await streamAgentChat({ message: trimmed, signal: controller.signal, onEvent });
    } catch (error) {
      // Cancel any pending animation frame so no stale flush runs after unmount.
      if (rafId !== 0) {
        cancelAnimationFrame(rafId);
        rafId = 0;
        pendingDelta = "";
      }
      // User-initiated stop (or unmount) is not an error state.
      const aborted =
        error instanceof DOMException && error.name === "AbortError";
      if (!terminalReceived && !aborted && !controller.signal.aborted) {
        setMessages((previous) =>
          previous.map((message) =>
            message.id === agentMessage.id
              ? {
                  ...message,
                  content: "The agent could not be reached. Please try again.",
                  failed: true,
                }
              : message,
          ),
        );
      }
    } finally {
      // Cancel any remaining animation frame.
      if (rafId !== 0) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }

      // --- Stream lifecycle finalization ---
      //
      // Every stream MUST reach a terminal state so the typing indicator
      // never gets stuck. Three cases:
      //
      //  1. Aborted (user clicked stop OR new message sent):
      //     - If the agent bubble is still empty, remove it — it was never
      //       completed and showing an empty bubble is confusing.
      //     - If it has partial content, keep it — the user chose to stop
      //       mid-stream and may want to see what was generated.
      //
      //  2. Stream ended without a terminal event (connection drop, server
      //     crash, malformed SSE):
      //     - Mark the agent message as failed so the user sees an error
      //       instead of a permanent typing indicator.
      //
      //  3. Normal completion (terminal event received):
      //     - Nothing extra needed; the done/error handler already set the
      //       final state.
      const aborted = controller.signal.aborted;
      if (aborted) {
        // Case 1: Remove empty agent bubbles left by aborted streams.
        setMessages((previous) => {
          const agentMsg = previous.find((m) => m.id === agentMessage.id);
          if (agentMsg && !agentMsg.content) {
            return previous.filter((m) => m.id !== agentMessage.id);
          }
          return previous;
        });
      } else if (!terminalReceived) {
        // Case 2: Stream ended without done/error — finalize as failed.
        setMessages((previous) =>
          previous.map((message) =>
            message.id === agentMessage.id && !message.content
              ? {
                  ...message,
                  content:
                    "The stream ended unexpectedly. Please try again.",
                  failed: true,
                }
              : message,
          ),
        );
      }
      // Case 3: Terminal event received — already handled.

      activeStreamsRef.current -= 1;
      if (activeStreamsRef.current === 0) setSending(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return { messages, sending, activeAgent, send, stop };
}
