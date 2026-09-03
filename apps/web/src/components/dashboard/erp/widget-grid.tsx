"use client";

import { useEffect, useState } from "react";

import { getWidget, type WidgetDefinition } from "@/lib/dashboard/widget-registry";
import { cn } from "@/lib/utils";

export interface LayoutItem {
  id: string;
  order: number;
  cols: 1 | 2 | 3 | 4;
  visible: boolean;
}

interface WidgetGridProps {
  /** The layout to render. Widgets not in the registry are silently skipped. */
  layout: LayoutItem[];
  /** Called when a widget becomes visible (for telemetry). */
  onWidgetShow?: (widgetId: string) => void;
  /** CSS class on the outer container. */
  className?: string;
}

/**
 * Renders a configurable grid of dashboard widgets from a layout definition.
 *
 * The grid uses a responsive 4-column layout:
 * - Mobile: 1 column
 * - sm: 2 columns
 * - lg: 4 columns
 *
 * Each widget's `cols` value determines its column span (1-4). Widgets
 * with `visible: false` are not rendered.
 */
export function WidgetGrid({ layout, onWidgetShow, className }: WidgetGridProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Sort by order, filter visible
  const sorted = [...layout]
    .filter((item) => item.visible)
    .sort((a, b) => a.order - b.order);

  if (!mounted) {
    // SSR-safe: render nothing on first pass, hydrate with layout
    return null;
  }

  return (
    <div
      className={cn(
        "grid gap-4 sm:grid-cols-2 lg:grid-cols-4",
        className,
      )}
    >
      {sorted.map((item) => {
        const widget = getWidget(item.id);
        if (!widget) return null;
        return (
          <WidgetCell
            key={item.id}
            widget={widget}
            cols={item.cols}
            onShow={onWidgetShow}
          />
        );
      })}
    </div>
  );
}

interface WidgetCellProps {
  widget: WidgetDefinition;
  cols: number;
  onShow?: (widgetId: string) => void;
}

function WidgetCell({ widget, cols, onShow }: WidgetCellProps) {
  const Component = widget.component;

  useEffect(() => {
    onShow?.(widget.id);
  }, [widget.id, onShow]);

  // Map cols to Tailwind grid column spans
  const spanClass =
    cols === 1
      ? "sm:col-span-1"
      : cols === 2
        ? "sm:col-span-2"
        : cols === 3
          ? "sm:col-span-2 lg:col-span-3"
          : "sm:col-span-2 lg:col-span-4";

  return (
    <div className={cn("min-w-0", spanClass)}>
      <Component />
    </div>
  );
}
