import { apiFetch, apiPost } from "@/lib/api/http";

const NARRATOR = "/api/v1/ai/narrator";

export type DigestStatus = "generated" | "abstained";
export type DigestSource = "live" | "cache" | "abstention" | "llm_disabled" | "unparseable";

export interface Digest {
  status: DigestStatus;
  source: DigestSource;
  as_of: string;
  title: string | null;
  summary: string | null;
  points: string[];
  caveat: string | null;
  generated_at: string | null;
  model_used: string | null;
  signals: Record<string, unknown> | null;
}

function queryString(asOf?: string): string {
  return asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
}

export function getDigest(asOf?: string): Promise<Digest> {
  return apiFetch<Digest>(`${NARRATOR}/digest${queryString(asOf)}`);
}

export function refreshDigest(asOf?: string): Promise<Digest> {
  return apiPost<Digest>(`${NARRATOR}/digest/refresh${queryString(asOf)}`, {});
}
