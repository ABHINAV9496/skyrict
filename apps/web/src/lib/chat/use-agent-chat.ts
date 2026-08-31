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
 */

import { flushSync } from "react-dom";
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
  send: (content: string) => Promise<void>;
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

export function useAgentChat(
  initialMessages: AgentChatMessage[],
  options?: { initialMessagesComplete?: boolean },
): AgentChatState {
  const [messages, setMessages] = useState<AgentChatMessage[]>(initialMessages);
  const [sending, setSending] = useState(false);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);

  // Use a ref so the send callback always reads the latest value without
  // needing to recreate the callback on prop changes.
  const initialCompleteRef = useRef(options?.initialMessagesComplete ?? false);
  const autoAppendedRef = useRef(false);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(async (content: string) => {
    const trimmed = content.trim();
    if (!trimmed || sendingRef.current) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    sendingRef.current = true;
    setSending(true);
    setActiveAgent(null);

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

    // When initialMessagesComplete is true the server already stored the user
    // message — skip appending it on the very first auto-send so the UI stays
    // consistent; subsequent sends always append both bubbles.
    const shouldAppendUser = !(initialCompleteRef.current && !autoAppendedRef.current);
    autoAppendedRef.current = true;

    // flushSync ensures the agent bubble is committed to the DOM *before* we
    // open the SSE stream.  Without this, a fast 401 from the upstream would
    // race the React batch and the error handler's setMessages would not find
    // the agent bubble — leaving it stuck on the loading dots forever.
    flushSync(() => {
      setMessages((previous) =>
        shouldAppendUser
          ? [...previous, userMessage, agentMessage]
          : [...previous, agentMessage],
      );
    });

    const appendDelta = (delta: string) => {
      setMessages((previous) =>
        previous.map((message) =>
          message.id === agentMessage.id
            ? { ...message, content: message.content + delta }
            : message,
        ),
      );
    };

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
          setActiveAgent(null);
          break;
        case "error":
          setMessages((previous) =>
            previous.map((message) =>
              message.id === agentMessage.id
                ? {
                    ...message,
                    content: "The agent could not complete this turn. Please try again.",
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
      // User-initiated stop (or unmount) is not an error state.
      const aborted =
        error instanceof DOMException && error.name === "AbortError";
      if (!aborted && !controller.signal.aborted) {
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
      sendingRef.current = false;
      setSending(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return { messages, sending, activeAgent, send, stop };
}
