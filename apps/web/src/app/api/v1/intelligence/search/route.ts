import { NextResponse } from "next/server";

import { searchIntelligence } from "@/lib/mock/intelligence";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q")?.trim();
  if (!q) {
    return NextResponse.json({ detail: "Missing 'q' query parameter." }, { status: 422 });
  }
  return NextResponse.json({ data: searchIntelligence(q) });
}
