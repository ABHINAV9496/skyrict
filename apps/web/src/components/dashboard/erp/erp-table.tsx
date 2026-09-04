"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface ErpColumn<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  /** Custom cell renderer; falls back to a plain string conversion. */
  render?: (row: T) => ReactNode;
  className?: string;
}

interface ErpTableProps<T> {
  columns: ErpColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  footer?: ReactNode;
  emptyMessage?: string;
}

/**
 * A shared, styled data table for ERP pages. Follows the existing DataTable
 * visual language (rounded card, muted header, hover rows) but is decoupled
 * from the mock payload shape so real API rows can render arbitrary cells.
 */
export function ErpTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  footer,
  emptyMessage = "No rows yet.",
}: ErpTableProps<T>) {
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
                    column.className,
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-10 text-center text-sm text-muted-foreground"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30",
                    onRowClick && "cursor-pointer",
                  )}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        "px-4 py-3 text-foreground",
                        column.align === "right" && "text-right tabular-nums",
                        column.className,
                      )}
                    >
                      {column.render
                        ? column.render(row)
                        : String((row as Record<string, unknown>)[column.key] ?? "-")}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {footer ? (
        <div className="border-t border-border/60 px-4 py-2.5">{footer}</div>
      ) : null}
    </div>
  );
}
