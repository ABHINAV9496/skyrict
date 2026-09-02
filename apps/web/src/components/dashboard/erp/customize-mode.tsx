"use client";

import { useCallback, useState } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AlertCircle, Eye, EyeOff, GripVertical, Minus, Plus, RotateCcw, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getWidget, type WidgetDefinition } from "@/lib/dashboard/widget-registry";
import { cn } from "@/lib/utils";

export interface CustomizeLayoutItem {
  id: string;
  order: number;
  cols: 1 | 2 | 3 | 4;
  visible: boolean;
}

interface CustomizeModeProps {
  /** Current layout. */
  layout: CustomizeLayoutItem[];
  /** Called when the user saves changes. */
  onSave: (layout: CustomizeLayoutItem[]) => Promise<void> | void;
  /** Called when the user resets to default. */
  onReset: () => Promise<void> | void;
  /** Called to close the customize panel. */
  onClose: () => void;
  /** Called when the user requests an AI suggestion. */
  onAiSuggestion?: () => void;
  /** Whether an AI suggestion is loading. */
  aiLoading?: boolean;
  /** Error message if save/reset failed. */
  errorNotice?: string | null;
  /** Whether save is in progress. */
  isSaving?: boolean;
}

/**
 * Full-screen customize mode for the ERP dashboard.
 *
 * Features:
 * - Drag-and-drop reorder (via @dnd-kit)
 * - Show/hide toggle per widget
 * - Size presets (1-col, 2-col, 3-col, full-width)
 * - Reset to default button
 * - AI suggestion button
 */
export function CustomizeMode({
  layout,
  onSave,
  onReset,
  onClose,
  onAiSuggestion,
  aiLoading,
  errorNotice,
  isSaving,
}: CustomizeModeProps) {
  const [localLayout, setLocalLayout] = useState<CustomizeLayoutItem[]>(layout);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      setLocalLayout((prev) => {
        const oldIndex = prev.findIndex((item) => item.id === active.id);
        const newIndex = prev.findIndex((item) => item.id === over.id);
        if (oldIndex === -1 || newIndex === -1) return prev;
        const reordered = arrayMove(prev, oldIndex, newIndex);
        return reordered.map((item, i) => ({ ...item, order: i }));
      });
    },
    [],
  );

  const toggleVisibility = useCallback((id: string) => {
    setLocalLayout((prev) =>
      prev.map((item) => (item.id === id ? { ...item, visible: !item.visible } : item)),
    );
  }, []);

  const setCols = useCallback((id: string, cols: number) => {
    setLocalLayout((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, cols: Math.max(1, Math.min(4, cols)) as 1 | 2 | 3 | 4 } : item,
      ),
    );
  }, []);

  const handleSave = useCallback(() => {
    onSave(localLayout);
  }, [localLayout, onSave]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <h2 className="font-display text-lg font-semibold text-foreground">
            Customize Dashboard
          </h2>
          <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
            {localLayout.filter((item) => item.visible).length} widgets
          </span>
        </div>
        <div className="flex items-center gap-2">
          {onAiSuggestion && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onAiSuggestion}
              disabled={aiLoading}
            >
              <Sparkles aria-hidden="true" className="mr-1.5 size-3.5" />
              {aiLoading ? "Thinking..." : "AI Suggest"}
            </Button>
          )}
          <Button type="button" variant="outline" size="sm" onClick={onReset}>
            <RotateCcw aria-hidden="true" className="mr-1.5 size-3.5" />
            Reset
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            <X aria-hidden="true" className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* Sortable widget list */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {errorNotice && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            <span>{errorNotice}</span>
          </div>
        )}
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={localLayout.map((item) => item.id)} strategy={verticalListSortingStrategy}>
            <div className="space-y-2">
              {localLayout.map((item) => (
                <SortableWidgetRow
                  key={item.id}
                  item={item}
                  widget={getWidget(item.id)}
                  onToggleVisibility={toggleVisibility}
                  onSetCols={setCols}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4">
        <Button type="button" variant="outline" onClick={onClose} disabled={isSaving}>
          Cancel
        </Button>
        <Button type="button" onClick={handleSave} disabled={isSaving}>
          {isSaving ? "Saving..." : "Save Layout"}
        </Button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Sortable widget row                                                       */
/* -------------------------------------------------------------------------- */

interface SortableWidgetRowProps {
  item: CustomizeLayoutItem;
  widget: WidgetDefinition | undefined;
  onToggleVisibility: (id: string) => void;
  onSetCols: (id: string, cols: number) => void;
}

function SortableWidgetRow({
  item,
  widget,
  onToggleVisibility,
  onSetCols,
}: SortableWidgetRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  if (!widget) return null;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 transition-shadow",
        isDragging && "shadow-lg ring-2 ring-primary/20",
        !item.visible && "opacity-50",
      )}
    >
      {/* Drag handle */}
      <button
        type="button"
        className="shrink-0 cursor-grab touch-none text-muted-foreground hover:text-foreground"
        {...attributes}
        {...listeners}
      >
        <GripVertical aria-hidden="true" className="size-4" />
      </button>

      {/* Widget info */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{widget.title}</p>
        <p className="text-xs text-muted-foreground">{widget.description}</p>
      </div>

      {/* Size controls */}
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={() => onSetCols(item.id, item.cols - 1)}
          disabled={item.cols <= widget.minCols}
          aria-label="Decrease width"
        >
          <Minus aria-hidden="true" className="size-3" />
        </Button>
        <span className="w-6 text-center text-xs font-medium text-muted-foreground">
          {item.cols}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="size-7 p-0"
          onClick={() => onSetCols(item.id, item.cols + 1)}
          disabled={item.cols >= widget.maxCols}
          aria-label="Increase width"
        >
          <Plus aria-hidden="true" className="size-3" />
        </Button>
      </div>

      {/* Visibility toggle */}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="size-7 p-0"
        onClick={() => onToggleVisibility(item.id)}
        aria-label={item.visible ? "Hide widget" : "Show widget"}
      >
        {item.visible ? (
          <Eye aria-hidden="true" className="size-3.5 text-foreground" />
        ) : (
          <EyeOff aria-hidden="true" className="size-3.5 text-muted-foreground" />
        )}
      </Button>
    </div>
  );
}
