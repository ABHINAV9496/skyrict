"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { TablePayload } from "@/lib/mock/erp";

export function DataTable({ payload }: { payload: TablePayload }) {
  const { columns, rows } = payload;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={cn(
                    "px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase",
                    column.align === "right" && "text-right",
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={index}
                className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-4 py-3 text-foreground",
                      column.align === "right" && "text-right tabular-nums",
                    )}
                  >
                    {String(row[column.key] ?? "-")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-border/60 px-4 py-2.5 text-xs text-muted-foreground">
        {rows.length} row{rows.length === 1 ? "" : "s"}
      </p>
    </div>
  );
}

export function DataTableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-6 border-b border-border bg-muted/40 px-4 py-3">
        <Skeleton className="h-3 w-1/4 rounded-full" />
        <Skeleton className="h-3 w-1/3 rounded-full" />
        <Skeleton className="ml-auto h-3 w-16 rounded-full" />
      </div>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center gap-6 border-b border-border/60 px-4 py-3.5 last:border-0"
        >
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function DataTableLoading() {
  return <DataTableSkeleton />;
}
