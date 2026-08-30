"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpenText, RefreshCw, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getDigest, refreshDigest, type Digest } from "@/lib/api/ai-api";
import { ApiError } from "@/lib/api/http";

type CardState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; digest: Digest };

function formatDate(asOf: string): string {
  const date = new Date(`${asOf}T00:00:00`);
  if (Number.isNaN(date.getTime())) return asOf;
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * SKY-63 cross-module intelligence narrator: a daily executive digest joining
 * Finance × Sales × Inventory × CRM signals, rendered at the top of the ERP
 * workspace home.
 */
export function DigestCard() {
  const [status, setStatus] = useState<CardState>({ state: "loading" });

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const digest = await getDigest();
      setStatus({ state: "ready", digest });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the daily digest.",
      });
    }
  }, []);

  const handleRefresh = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const digest = await refreshDigest();
      setStatus({ state: "ready", digest });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not regenerate the digest.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="h-4 w-40 rounded bg-muted" />
        <div className="mt-4 space-y-2">
          <div className="h-3 w-full rounded bg-muted" />
          <div className="h-3 w-5/6 rounded bg-muted" />
          <div className="h-3 w-2/3 rounded bg-muted" />
        </div>
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-5 py-4">
        <div className="flex items-center gap-3">
          <BookOpenText aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{status.message}</p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" className="size-3.5" />
          Retry
        </Button>
      </div>
    );
  }

  const { digest } = status;
  const isGenerated = digest.status === "generated" && digest.title !== null;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Sparkles aria-hidden="true" className="size-5" />
          </div>
          <div>
            <h3 className="font-display text-base font-semibold text-foreground">
              Intelligence digest
            </h3>
            <p className="text-xs text-muted-foreground">
              {formatDate(digest.as_of)}
              {digest.model_used ? ` · ${digest.model_used}` : ""}
            </p>
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => void handleRefresh()}>
          <RefreshCw aria-hidden="true" className="size-3.5" />
          Refresh
        </Button>
      </div>

      <div className="px-5 py-4">
        {isGenerated ? (
          <div className="space-y-3">
            <p className="font-display text-lg font-semibold text-foreground">{digest.title}</p>
            {digest.summary ? (
              <p className="text-sm leading-relaxed text-muted-foreground">{digest.summary}</p>
            ) : null}
            {digest.points.length > 0 ? (
              <ul className="space-y-2">
                {digest.points.map((point, index) => (
                  <li key={index} className="flex gap-2.5 text-sm text-muted-foreground">
                    <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-primary/70" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {digest.caveat ?? "No material cross-module activity to report today."}
          </p>
        )}
      </div>
    </div>
  );
}
