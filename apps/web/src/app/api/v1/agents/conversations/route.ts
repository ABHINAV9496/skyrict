import { NextResponse } from "next/server";

import { createConversation, listConversations } from "@/lib/mock/agents-store";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ data: listConversations() });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    title?: string;
    prompt?: string;
  };
  const conversation = createConversation(
    body.title ?? "New chat",
    typeof body.prompt === "string" ? body.prompt : undefined,
  );
  return NextResponse.json({ data: conversation }, { status: 201 });
}
