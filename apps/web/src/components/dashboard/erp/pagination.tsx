"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  onPageChange: (offset: number) => void;
  className?: string;
}

/**
 * Offset/limit pagination matching the backend's list contract. Renders the
 * visible range ("1–50 of 137") plus previous/next controls that page through
 * `offset` in `limit` steps.
 */
export function Pagination({ offset, limit, total, onPageChange, className }: PaginationProps) {
  if (total === 0) return null;

  const start = offset + 1;
  const end = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = end < total;

  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <p className="text-xs text-muted-foreground">
        Showing <span className="font-medium text-foreground tabular-nums">{start}</span>–
        <span className="font-medium text-foreground tabular-nums">{end}</span> of{" "}
        <span className="font-medium text-foreground tabular-nums">{total}</span>
      </p>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          aria-label="Previous page"
          disabled={!hasPrevious}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          aria-label="Next page"
          disabled={!hasNext}
          onClick={() => onPageChange(offset + limit)}
        >
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
