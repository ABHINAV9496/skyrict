"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface FinanceColumn<T> {
  label: string;
  align?: "left" | "right";
  headerClassName?: string;
  cellClassName?: string;
  render: (row: T) => ReactNode;
}

interface FinanceTableProps<T> {
  columns: FinanceColumn<T>[];
  rows: T[];
  getKey: (row: T) => string;
  footer?: ReactNode;
  emptyMessage?: string;
}

/** Typed table with the same visual language as the shared ERP DataTable. */
export function FinanceTable<T>({
  columns,
  rows,
  getKey,
  footer,
  emptyMessage,
}: FinanceTableProps<T>) {
  if (rows.length === 0) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
          <p className="text-sm text-muted-foreground">{emptyMessage ?? "Nothing here yet."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              {columns.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className={cn(
                    "px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase",
                    column.align === "right" && "text-right",
                    column.headerClassName,
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={getKey(row)}
                className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
              >
                {columns.map((column) => (
                  <td
                    key={column.label}
                    className={cn(
                      "px-4 py-3 text-foreground",
                      column.align === "right" && "text-right tabular-nums",
                      column.cellClassName,
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {footer ? (
        <div className="border-t border-border/60 bg-muted/20 px-4 py-2.5 text-sm">{footer}</div>
      ) : null}
    </div>
  );
}
