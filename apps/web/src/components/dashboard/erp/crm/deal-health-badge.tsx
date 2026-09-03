"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle, Info, Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/http";
import { getDealHealth, type DealHealth } from "@/lib/api/crm-ai-api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Health band styles - green | yellow | red
// ---------------------------------------------------------------------------

const HEALTH_STYLES: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  yellow: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  red: "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
};

const HEALTH_LABELS: Record<string, string> = {
  green: "Healthy",
  yellow: "At Risk",
  red: "Critical",
};

const HEALTH_ICONS: Record<string, typeof Info> = {
  green: CheckCircle,
  yellow: AlertTriangle,
  red: AlertTriangle,
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DealHealthBadgeProps {
  opportunityId: string;
  /** When true the badge is shown inline (no wrapper card). */
  inline?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DealHealthBadge({ opportunityId, inline = false }: DealHealthBadgeProps) {
  const [health, setHealth] = useState<DealHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getDealHealth(opportunityId);
      setHealth(res);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not load deal health.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [opportunityId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <Loader2
        aria-label="Loading deal health"
        className="size-4 animate-spin text-muted-foreground"
      />
    );
  }

  if (error || !health) {
    return (
      <span className="text-xs text-muted-foreground">{error ?? "No health data"}</span>
    );
  }

  const Icon = HEALTH_ICONS[health.health] ?? Info;

  const badge = (
    <Badge
      variant="secondary"
      className={cn("text-xs font-semibold", HEALTH_STYLES[health.health])}
      title={[
        ...health.risk_factors.map((r) => `Risk: ${r}`),
        ...health.recommended_actions.map((a) => `Action: ${a}`),
      ].join("\n")}
    >
      <Icon aria-hidden="true" className="mr-1 size-3" />
      {HEALTH_LABELS[health.health] ?? health.health}
    </Badge>
  );

  if (inline) return badge;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        {badge}
        <Button
          variant="ghost"
          size="icon"
          className="size-6"
          onClick={() => void load()}
          title="Refresh health"
        >
          <RefreshCw className="size-3" />
        </Button>
      </div>
      {health.risk_factors.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Risk factors
          </p>
          <ul className="space-y-0.5">
            {health.risk_factors.map((r) => (
              <li key={r} className="text-xs text-muted-foreground flex items-start gap-1.5">
                <AlertTriangle aria-hidden="true" className="mt-0.5 size-3 shrink-0 text-amber-500" />
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {health.recommended_actions.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Recommended actions
          </p>
          <ul className="space-y-0.5">
            {health.recommended_actions.map((a) => (
              <li key={a} className="text-xs text-muted-foreground flex items-start gap-1.5">
                <CheckCircle aria-hidden="true" className="mt-0.5 size-3 shrink-0 text-emerald-500" />
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[10px] text-muted-foreground">
        Confidence {Math.round(health.confidence * 100)}%
        {health.days_in_stage != null && ` · ${health.days_in_stage}d in stage`}
      </p>
    </div>
  );
}
