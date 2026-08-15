"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import {
  arrow,
  autoUpdate,
  flip,
  offset,
  shift,
  useFloating,
} from "@floating-ui/react";

import { Button } from "@/components/ui/button";
import type { TourStep } from "@/components/dashboard/tour/tour-steps";
import { cn } from "@/lib/utils";

const ARROW_SIZE = 10;
const STATIC_SIDE: Record<string, "top" | "right" | "bottom" | "left"> = {
  top: "bottom",
  right: "left",
  bottom: "top",
  left: "right",
};

interface TourTooltipProps {
  step: TourStep;
  index: number;
  total: number;
  referenceEl: HTMLElement | null;
  onBack: () => void;
  onNext: () => void;
  onClose: () => void;
}

export function TourTooltip({
  step,
  index,
  total,
  referenceEl,
  onBack,
  onNext,
  onClose,
}: TourTooltipProps) {
  const arrowRef = useRef<HTMLDivElement>(null);

  const { refs, floatingStyles, placement, middlewareData } = useFloating({
    placement: step.placement,
    strategy: "fixed",
    middleware: [
      offset(14),
      flip({ fallbackAxisSideDirection: "start" }),
      shift({ padding: 12 }),
      arrow({ element: arrowRef }),
    ],
    whileElementsMounted: autoUpdate,
  });

  useEffect(() => {
    if (referenceEl) {
      refs.setReference(referenceEl);
    }
  }, [referenceEl, refs]);

  const Icon = step.icon;
  const isFirst = index === 0;
  const isLast = index === total - 1;

  const side = placement.split("-")[0];
  const arrowStyle: CSSProperties = {
    left: middlewareData.arrow?.x ?? undefined,
    top: middlewareData.arrow?.y ?? undefined,
    [STATIC_SIDE[side] ?? "bottom"]: -(ARROW_SIZE / 2),
  };

  const card = (
    <div className="relative w-[19rem] sm:w-80">
      {referenceEl ? (
        <div
          ref={arrowRef}
          aria-hidden="true"
          className="absolute z-0 size-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px] bg-popover"
          style={arrowStyle}
        />
      ) : null}
      <div
        role="dialog"
        aria-label={step.title}
        className="relative z-10 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-xl shadow-foreground/5 ring-1 ring-foreground/10"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex size-11 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon aria-hidden="true" className="size-5" />
          </div>
          <p className="pt-1 text-xs font-medium text-muted-foreground tabular-nums">
            {index + 1} / {total}
          </p>
        </div>

        <h3 className="mt-3 font-display text-base font-semibold tracking-tight text-foreground">
          {step.title}
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          {step.description}
        </p>

        <div className="mt-4 flex items-center justify-between gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Skip
          </Button>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isFirst}
              onClick={onBack}
            >
              Back
            </Button>
            <Button type="button" size="sm" onClick={onNext}>
              {isLast ? "Get started" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );

  if (!referenceEl) {
    return (
      <div className="pointer-events-none fixed inset-0 z-50 grid place-items-center">
        <div className="pointer-events-auto animate-in fade-in-0 zoom-in-95 duration-200">
          {card}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={refs.setFloating}
      style={floatingStyles}
      className={cn("z-50 animate-in fade-in-0 zoom-in-95 duration-200")}
    >
      {card}
    </div>
  );
}
