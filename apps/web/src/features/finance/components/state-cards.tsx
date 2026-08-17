import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

export function FinanceErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-6 py-12 text-center">
      <p className="text-sm font-medium text-destructive">{message}</p>
      {onRetry ? (
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function FinanceEmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-6 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Icon aria-hidden="true" className="size-5" />
      </div>
      <h3 className="mt-3 font-display text-sm font-semibold text-foreground">{title}</h3>
      <p className="mt-1 max-w-60 text-xs leading-relaxed text-muted-foreground">
        {description}
      </p>
    </div>
  );
}
