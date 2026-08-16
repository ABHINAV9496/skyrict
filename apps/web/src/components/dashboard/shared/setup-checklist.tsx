"use client";

import Link from "next/link";
import { BadgeCheck, Circle, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface SetupStepAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

export interface SetupStep {
  key: string;
  label: string;
  description: string;
  /** Neutral steps (e.g. settings) are never counted toward completion. */
  checkable?: boolean;
  done?: boolean;
  action?: SetupStepAction;
}

/**
 * Onboarding checklist for a module home. Renders a progress line plus one row
 * per step: a status icon, the label/description, and (when an action is given)
 * a button or link. Hides entirely once every checkable step is done.
 */
export function SetupChecklist({
  title,
  description,
  steps,
}: {
  title: string;
  description?: string;
  steps: SetupStep[];
}) {
  const checkable = steps.filter((step) => step.checkable !== false);
  const doneCount = checkable.filter((step) => step.done).length;
  const complete = checkable.length > 0 && doneCount === checkable.length;

  if (complete) return null;

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            {title}
          </h2>
          {description ? (
            <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <span className="text-xs font-medium text-muted-foreground">
          {doneCount} of {checkable.length} done
        </span>
      </div>

      <div className="mt-3 divide-y divide-border">
        {steps.map((step) => {
          const neutral = step.checkable === false;
          const done = !neutral && Boolean(step.done);
          const action = step.action;
          return (
            <div key={step.key} className="flex items-center gap-3 py-3">
              {neutral ? (
                <SlidersHorizontal
                  aria-hidden="true"
                  className="size-5 shrink-0 text-muted-foreground"
                />
              ) : done ? (
                <BadgeCheck
                  aria-hidden="true"
                  className="size-5 shrink-0 text-emerald-500"
                />
              ) : (
                <Circle
                  aria-hidden="true"
                  className="size-5 shrink-0 text-muted-foreground/70"
                />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{step.label}</p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {step.description}
                </p>
              </div>
              {done ? (
                <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  Done
                </span>
              ) : action ? (
                action.href ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={action.href}>{action.label}</Link>
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={action.onClick}
                  >
                    {action.label}
                  </Button>
                )
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Loading skeleton mirroring SetupChecklist's card layout. */
export function SetupChecklistSkeleton() {
  return (
    <section className={cn("rounded-xl border border-border bg-card p-5")}>
      <div className="h-4 w-40 rounded-full bg-muted" />
      <div className="mt-3 divide-y divide-border">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex items-center gap-3 py-3">
            <div className="size-5 rounded-full bg-muted" />
            <div className="min-w-0 flex-1">
              <div className="h-3.5 w-1/3 rounded-full bg-muted" />
              <div className="mt-1.5 h-3 w-2/3 rounded-full bg-muted" />
            </div>
            <div className="h-8 w-20 rounded-md bg-muted" />
          </div>
        ))}
      </div>
    </section>
  );
}
