"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FollowUpCard } from "@/components/dashboard/erp/crm/follow-up-card";
import { ApiError } from "@/lib/api/http";
import { listFollowUps, type FollowUpItem } from "@/lib/api/crm-ai-api";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; items: FollowUpItem[] };

export function FollowUpsFeed() {
  const [status, setStatus] = useState<Status>({ state: "loading" });

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const items = await listFollowUps();
      setStatus({ state: "ready", items });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not load follow-ups.";
      setStatus({ state: "error", message: msg });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (status.state === "error") {
    return <p className="text-sm text-destructive py-8 text-center">{status.message}</p>;
  }

  const { items } = status;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
          Follow-ups
        </h2>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" className="mr-1.5 size-4" />
          Refresh
        </Button>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center">
          No pending follow-ups.
        </p>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <FollowUpCard key={item.id} item={item} onAction={() => void load()} />
          ))}
        </div>
      )}
    </div>
  );
}
