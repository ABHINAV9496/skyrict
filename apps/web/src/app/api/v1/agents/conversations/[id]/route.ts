import { NextResponse } from "next/server";

import { appendMessage, getConversation } from "@/lib/mock/agents-store";

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
  const body = (await request.json().catch(() => ({}))) as { content?: string };
  const prompt = (body.content ?? "").trim();
  if (!prompt) {
    return NextResponse.json({ detail: "Message content is required." }, { status: 422 });
  }

  const conversation = appendMessage(id, "user", prompt);
  if (!conversation) {
    return NextResponse.json({ detail: "Conversation not found." }, { status: 404 });
  }

  return NextResponse.json({ data: conversation });
}
