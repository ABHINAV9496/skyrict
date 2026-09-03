"use client";

import { useCallback, useState } from "react";
import { Check, ChevronDown, ChevronUp, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getWidget } from "@/lib/dashboard/widget-registry";
import { cn } from "@/lib/utils";

export interface SuggestionLayoutItem {
  id: string;
  order: number;
  cols: 1 | 2 | 3 | 4;
  visible: boolean;
}

interface AiSuggestionPreviewProps {
  /** The AI-suggested layout. */
  suggestedLayout: SuggestionLayoutItem[];
  /** The user's reasoning from the AI. */
  reasoning: string;
  /** Confidence score (0-1). */
  confidence: number;
  /** Called when the user accepts the suggestion. */
  onApply: (layout: SuggestionLayoutItem[]) => void;
  /** Called when the user dismisses the suggestion. */
  onDismiss: () => void;
}

/**
 * Renders a diff preview of the AI-suggested layout changes.
 *
 * Shows each widget with its proposed changes (reorder, resize, hide)
 * highlighted, the AI's reasoning, and Apply/Dismiss buttons.
 */
export function AiSuggestionPreview({
  suggestedLayout,
  reasoning,
  confidence,
  onApply,
  onDismiss,
}: AiSuggestionPreviewProps) {
  const [expanded, setExpanded] = useState(true);

  const handleApply = useCallback(() => {
    onApply(suggestedLayout);
  }, [suggestedLayout, onApply]);

  return (
    <div className="overflow-hidden rounded-xl border border-primary/30 bg-primary/5">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-2">
          <Sparkles aria-hidden="true" className="size-4 text-primary" />
          <span className="text-sm font-medium text-foreground">AI Suggestion</span>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              confidence >= 0.7
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
            )}
          >
            {Math.round(confidence * 100)}% confident
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={() => setExpanded(!expanded)}>
            {expanded ? (
              <ChevronUp aria-hidden="true" className="size-3.5" />
            ) : (
              <ChevronDown aria-hidden="true" className="size-3.5" />
            )}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onDismiss}>
            <X aria-hidden="true" className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* Reasoning */}
      {expanded && (
        <div className="border-t border-primary/20 px-5 py-3">
          <p className="text-sm text-muted-foreground">{reasoning}</p>

          {/* Widget change list */}
          <div className="mt-3 space-y-1.5">
            {suggestedLayout.map((item) => {
              const widget = getWidget(item.id);
              if (!widget) return null;
              return (
                <div
                  key={item.id}
                  className="flex items-center gap-2 text-sm"
                >
                  <span
                    className={cn(
                      "size-1.5 shrink-0 rounded-full",
                      item.visible ? "bg-emerald-500" : "bg-muted-foreground/30",
                    )}
                  />
                  <span className={cn("font-medium", !item.visible && "line-through opacity-50")}>
                    {widget.title}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.visible ? `${item.cols} col${item.cols > 1 ? "s" : ""}` : "hidden"}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Apply button */}
          <div className="mt-4 flex justify-end">
            <Button type="button" size="sm" onClick={handleApply}>
              <Check aria-hidden="true" className="mr-1.5 size-3.5" />
              Apply Suggestion
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
