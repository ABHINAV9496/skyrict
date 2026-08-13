"use client";

import { LoaderCircle } from "lucide-react";

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
                    {String(row[column.key] ?? "—")}
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

export function DataTableSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="space-y-0 p-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    </div>
  );
}

export function DataTableLoading() {
  return (
    <div className="flex items-center justify-center rounded-xl border border-border bg-card p-10">
      <LoaderCircle aria-hidden="true" className="size-5 animate-spin text-primary" />
    </div>
  );
}
