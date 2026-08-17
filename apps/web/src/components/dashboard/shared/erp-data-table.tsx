"use client";

import type { ReactNode } from "react";

import { Pagination } from "@/components/dashboard/shared/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import type { PaginationMeta } from "@/lib/api/http";
import { cn } from "@/lib/utils";

export interface ErpColumn<T> {
  key: keyof T & string;
  label: string;
  align?: "left" | "right";
  className?: string;
  render?: (row: T) => ReactNode;
}

/**
 * Typed ERP table over a `Paginated<T>`. Mirrors the shared DataTable's chrome
 * (rounded card, muted header, `px-4 py-3` rows) and adds numbered pagination.
 * `meta.total` is a progressive estimate when a following page exists, so the
 * footer reports the visible count rather than a precise grand total.
 */
export function ErpDataTable<T extends { id: string }>({
  columns,
  rows,
  meta,
  onPageChange,
  onRowClick,
}: {
  columns: ErpColumn<T>[];
  rows: T[];
  meta: PaginationMeta;
  onPageChange?: (page: number) => void;
  onRowClick?: (row: T) => void;
}) {
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
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-12 text-center text-sm text-muted-foreground"
                >
                  No records found.
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-b border-border/60 transition-colors last:border-0",
                    onRowClick && "cursor-pointer hover:bg-muted/30",
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
                        : String(row[column.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 px-4 py-2.5">
        <p className="text-xs text-muted-foreground">
          Showing {rows.length} record{rows.length === 1 ? "" : "s"}
          {meta.total_pages > 1 ? (
            <>
              {" "}
              · Page {meta.page} of {meta.total_pages}
            </>
          ) : null}
        </p>
        {onPageChange && meta.total_pages > 1 ? (
          <Pagination meta={meta} onPageChange={onPageChange} />
        ) : null}
      </div>
    </div>
  );
}

/** Loading skeleton mirroring ErpDataTable's structure. */
export function ErpDataTableSkeleton({ columns = 5 }: { columns?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-6 border-b border-border bg-muted/40 px-4 py-3">
        {Array.from({ length: Math.min(columns, 4) }).map((_, index) => (
          <Skeleton key={index} className="h-3 w-1/4 rounded-full" />
        ))}
        <Skeleton className="ml-auto h-3 w-16 rounded-full" />
      </div>
      {Array.from({ length: 5 }).map((_, index) => (
        <div
          key={index}
          className="flex items-center gap-6 border-b border-border/60 px-4 py-3.5 last:border-0"
        >
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
      <div className="border-t border-border/60 px-4 py-2.5">
        <Skeleton className="h-3 w-24 rounded-full" />
      </div>
    </div>
  );
}
