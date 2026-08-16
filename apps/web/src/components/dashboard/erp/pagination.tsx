"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface PageMeta {
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

/** Derive a `PageMeta` from the offset/limit form used by list callers. */
export function offsetMeta(
  offset: number,
  limit: number,
  total: number,
): PageMeta {
  return {
    total,
    page: Math.floor(offset / limit) + 1,
    pageSize: limit,
    totalPages: Math.max(1, Math.ceil(total / limit)),
  };
}

interface PaginationProps {
  meta: PageMeta;
  onPageChange: (page: number) => void;
  className?: string;
}

/**
 * Page-based pagination matching the backend's offset/limit list contract.
 * Renders the visible range ("1–50 of 137") plus previous/next controls that
 * page through the list in `pageSize` steps.
 */
export function Pagination({ meta, onPageChange, className }: PaginationProps) {
  if (meta.totalPages <= 1) return null;

  const start = (meta.page - 1) * meta.pageSize + 1;
  const end = Math.min(meta.page * meta.pageSize, meta.total);

  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <p className="text-xs text-muted-foreground">
        Showing <span className="font-medium text-foreground tabular-nums">{start}</span>–
        <span className="font-medium text-foreground tabular-nums">{end}</span> of{" "}
        <span className="font-medium text-foreground tabular-nums">{meta.total}</span>
      </p>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          aria-label="Previous page"
          disabled={meta.page <= 1}
          onClick={() => onPageChange(meta.page - 1)}
        >
          <ChevronLeft aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          aria-label="Next page"
          disabled={meta.page >= meta.totalPages}
          onClick={() => onPageChange(meta.page + 1)}
        >
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
