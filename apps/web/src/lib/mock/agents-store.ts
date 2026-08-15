/**
 * In-memory store for the AI Agents chat world.
 *
 * This is a frontend stub: conversations live in a module-level Map on the
 * server and reset when the process restarts. It exists so the chat UI can be
 * built against real route shapes (`GET /api/v1/agents/conversations`, etc.)
 * and later pointed at an agents service without changing the client.
 */

export type ChatRole = "user" | "agent";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

function newId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

/** Deterministic, conversational mock reply for a user prompt. */
function replyFor(prompt: string): string {
  const clean = prompt.trim();
  if (!clean) return "I'm ready when you are. What would you like to work on?";

  if (/(hello|hi|hey|yo)\b/i.test(clean)) {
    return "Hey! I'm your Skyrict agent. I can help with market research, drafting, analysis, and operational tasks. What's on your mind?";
  }
  if (/\?$/.test(clean) && /(how|what|why|when|where)/i.test(clean)) {
    return `Good question. Here's how I'd approach it: first I'd pull the relevant signals from your workspace and the market, then cross-check for conflicts, and finally summarize with a recommendation. Want me to start on "${clean.replace(/[?.]$/, "")}"?`;
  }
  if (/(report|summary|analy|trend|market|competit)/i.test(clean)) {
    return `On it. I'm scanning internal records and external sources for "${clean}". Based on what I'm seeing so far, the story breaks into three parts: current state, what changed recently, and what to watch next. I'll have a structured brief for you shortly.`;
  }
  if (/(draft|write|email|proposal|copy)/i.test(clean)) {
    return `Sure — I'll draft that for you. I'll keep it sharp and specific to your business, and I can adjust tone or length once you review the first pass. Give me a moment.`;
  }
  return `Understood — noted "${clean}". I'll reason through it across your data and the market, then come back with a concrete next step. In the meantime, tell me if you want me to prioritize speed, depth, or a short answer.`;
}

function seedConversations(): Conversation[] {
  const now = Date.now();
  return [
    {
      id: "demo-research",
      title: "Q3 market scan — logistics software",
      createdAt: new Date(now - 1000 * 60 * 60 * 26).toISOString(),
      updatedAt: minutesAgo(4),
      messages: [
        {
          id: "d1",
          role: "user",
          content: "Scan the market for logistics software trends this quarter.",
          createdAt: new Date(now - 1000 * 60 * 60 * 26).toISOString(),
        },
        {
          id: "d2",
          role: "agent",
          content:
            "Done. Logistics software searches are up ~30% with consolidation around automation and API-first tools. Competitors are bundling visibility with planning; the whitespace is in small-fleet operations. Full brief is in your Intelligence feed.",
          createdAt: new Date(now - 1000 * 60 * 60 * 25).toISOString(),
        },
      ],
    },
    {
      id: "demo-draft",
      title: "Draft partner outreach email",
      createdAt: new Date(now - 1000 * 60 * 60 * 30).toISOString(),
      updatedAt: minutesAgo(60 * 26),
      messages: [
        {
          id: "e1",
          role: "user",
          content: "Draft a short outreach email for potential channel partners.",
          createdAt: new Date(now - 1000 * 60 * 60 * 30).toISOString(),
        },
        {
          id: "e2",
          role: "agent",
          content:
            "Here's a draft:\n\nSubject: Quick question about partnering\n\nHi [Name],\n\nWe're [Company] and we help teams act on market signals. I'd love to explore whether a channel partnership makes sense for [Your Company] this quarter.\n\nOpen to a 20-minute call next week?\n\nBest,\n[You]\n\nWant me to tighten it, change the tone, or personalize it per partner?",
          createdAt: new Date(now - 1000 * 60 * 60 * 29).toISOString(),
        },
      ],
    },
  ];
}

const conversations = new Map<string, Conversation>(seedConversations().map((c) => [c.id, c]));

export function listConversations(): Conversation[] {
  return [...conversations.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function getConversation(id: string): Conversation | undefined {
  return conversations.get(id);
}

export function createConversation(title: string, firstPrompt?: string): Conversation {
  const now = new Date().toISOString();
  const conversation: Conversation = {
    id: newId(),
    title: title.trim() || "New chat",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
  conversations.set(conversation.id, conversation);
  if (firstPrompt?.trim()) {
    appendMessage(conversation.id, "user", firstPrompt);
  }
  return conversations.get(conversation.id)!;
}

export function appendMessage(
  id: string,
  role: ChatRole,
  content: string,
): Conversation | undefined {
  const conversation = conversations.get(id);
  if (!conversation) return undefined;
  const message: ChatMessage = {
    id: newId(),
    role,
    content,
    createdAt: new Date().toISOString(),
  };
  conversation.messages.push(message);
  conversation.updatedAt = message.createdAt;
  if (conversation.messages.length === 2 && role === "agent") {
    conversation.title = conversation.messages[0].content.slice(0, 48) || conversation.title;
  }
  return conversation;
}

export function nextAgentReply(prompt: string): string {
  return replyFor(prompt);
}
