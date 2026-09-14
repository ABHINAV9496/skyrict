import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function FinanceErrorState({
    message,
    onRetry,
    className,
}: {
    message: string;
    onRetry?: () => void;
    className?: string;
}) {
    return (
        <div
            className={cn(
                "flex flex-col items-center justify-center rounded-xl border border-border bg-card px-6 py-12 text-center",
                className,
            )}
        >
            <p className="text-sm font-medium text-destructive">{message}</p>
            {onRetry ? (
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={onRetry}
                >
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
    className,
}: {
    icon: LucideIcon;
    title: string;
    description: string;
    className?: string;
}) {
    return (
        <div
            className={cn(
                "flex flex-col items-center justify-center rounded-xl border border-border bg-card px-6 py-12 text-center",
                className,
            )}
        >
            <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Icon aria-hidden="true" className="size-5" />
            </div>
            <h3 className="mt-3 font-display text-sm font-semibold text-foreground">
                {title}
            </h3>
            <p className="mt-1 max-w-60 text-xs leading-relaxed text-muted-foreground">
                {description}
            </p>
        </div>
    );
}
