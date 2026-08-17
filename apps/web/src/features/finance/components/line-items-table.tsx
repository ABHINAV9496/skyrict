"use client";

import type { ReactNode } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface LineItemColumn {
  label: string;
  align?: "left" | "right";
  className?: string;
}

interface LineItemsTableProps {
  columns: LineItemColumn[];
  footer: ReactNode;
  addRowLabel?: string;
  onAddRow: () => void;
  children: ReactNode;
}

function LineItemsTable({
  columns,
  footer,
  addRowLabel = "Add line",
  onAddRow,
  children,
}: LineItemsTableProps) {
  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="max-h-[min(50vh,24rem)] overflow-y-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="sticky top-0 z-10 border-b border-border bg-muted">
                {columns.map((column, index) => (
                  <th
                    key={`${column.label}-${index}`}
                    scope="col"
                    className={cn(
                      "px-3 py-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase",
                      column.align === "right" && "text-right",
                      column.className,
                    )}
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>{children}</tbody>
          </table>
        </div>
        <div className="border-t border-border/60 bg-muted/20 px-3 py-2 text-sm">{footer}</div>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full border-dashed"
        onClick={onAddRow}
      >
        <Plus aria-hidden="true" className="size-3.5" />
        {addRowLabel}
      </Button>
    </div>
  );
}

export { LineItemsTable };
