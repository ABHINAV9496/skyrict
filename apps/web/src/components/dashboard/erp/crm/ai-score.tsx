"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/http";
import { scoreLead, type LeadScore } from "@/lib/api/crm-ai-api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Score colour buckets (green 80+ / amber 50-79 / red <50)
// ---------------------------------------------------------------------------

const SCORE_STYLES: Record<string, string> = {
  high: "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  medium: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  low: "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
};

function scoreBand(score: number): "high" | "medium" | "low" {
  if (score >= 80) return "high";
  if (score >= 50) return "medium";
  return "low";
}

function scoreLabel(score: number): string {
  if (score >= 80) return "Hot";
  if (score >= 50) return "Warm";
  return "Cold";
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AiScoreProps {
  leadId: string;
  /** When true the badge is shown inline (no wrapper card). */
  inline?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AiScore({ leadId, inline = false }: AiScoreProps) {
  const [score, setScore] = useState<LeadScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await scoreLead(leadId);
      setScore(res);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not compute score.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <Loader2
        aria-label="Loading lead score"
        className="size-4 animate-spin text-muted-foreground"
      />
    );
  }

  if (error || !score) {
    return (
      <span className="text-xs text-muted-foreground">{error ?? "No score"}</span>
    );
  }

  const band = scoreBand(score.score);
  const badge = (
    <Badge
      variant="secondary"
      className={cn("text-xs font-semibold tabular-nums", SCORE_STYLES[band])}
      title={score.factors.join(" · ")}
    >
      {score.score} · {scoreLabel(score.score)}
    </Badge>
  );

  if (inline) return badge;

  return (
    <div className="flex items-center gap-3">
      {badge}
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        onClick={() => void load()}
        title="Refresh score"
      >
        <RefreshCw className="size-3" />
      </Button>
      {score.factors.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {score.factors.map((f) => (
            <span
              key={f}
              className="inline-block rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
            >
              {f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
