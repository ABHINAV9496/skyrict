import { NextResponse } from "next/server";

import {
  appendMessage,
  deleteConversation,
  getConversation,
  renameConversation,
  togglePinConversation,
} from "@/lib/mock/agents-store";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const conversation = getConversation(id);
  if (!conversation) {
    return NextResponse.json({ detail: "Conversation not found." }, { status: 404 });
  }
  return NextResponse.json({ data: conversation });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = (await request.json().catch(() => ({}))) as {
    content?: string;
    role?: "user" | "agent";
  };
  const prompt = (body.content ?? "").trim();
  if (!prompt) {
    return NextResponse.json({ detail: "Message content is required." }, { status: 422 });
  }

  const role = body.role === "agent" ? "agent" : "user";
  const conversation = appendMessage(id, role, prompt);
  if (!conversation) {
    return NextResponse.json({ detail: "Conversation not found." }, { status: 404 });
  }

  return NextResponse.json({ data: conversation });
}

/** Rename or pin/unpin a conversation. */
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = (await request.json().catch(() => ({}))) as {
    title?: string;
    pin?: boolean;
  };
  if (typeof body.title === "string") {
    const conversation = renameConversation(id, body.title);
    if (!conversation) {
      return NextResponse.json({ detail: "Conversation not found." }, { status: 404 });
    }
    return NextResponse.json({ data: conversation });
  }
  if (typeof body.pin === "boolean") {
    // Honor an explicit target so the UI can set a known state.
    const conversation = togglePinConversation(id);
    if (!conversation) {
      return NextResponse.json({ detail: "Conversation not found." }, { status: 404 });
    }
    if (conversation.pinned !== body.pin) {
      conversation.pinned = body.pin;
    }
    return NextResponse.json({ data: conversation });
  }
  return NextResponse.json(
    { detail: "Provide a 'title' or 'pin' field to update the conversation." },
    { status: 422 },
  );
}

/** Delete a conversation. */
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!getConversation(id)) {
    return NextResponse.json({ detail: "Conversation not found." }, { status: 404 });
  }
  deleteConversation(id);
  return NextResponse.json({ data: { deleted: true } });
}
