"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PaginationMeta } from "@/lib/api/http";

/** Numbered page list with collapsed gaps (e.g. 1 … 4 5 6 … 12). */
function pageList(page: number, totalPages: number): (number | "ellipsis")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  const candidates = new Set([1, totalPages, page - 1, page, page + 1]);
  const pages = [...candidates]
    .filter((value) => value >= 1 && value <= totalPages)
    .sort((a, b) => a - b);
  const result: (number | "ellipsis")[] = [];
  let previous = 0;
  for (const value of pages) {
    if (value - previous > 1) result.push("ellipsis");
    result.push(value);
    previous = value;
  }
  return result;
}

export function Pagination({
  meta,
  onPageChange,
}: {
  meta: PaginationMeta;
  onPageChange: (page: number) => void;
}) {
  const { page, total_pages: totalPages } = meta;
  if (totalPages <= 1) return null;

  return (
    <nav
      aria-label="Pagination"
      className="flex items-center gap-1"
    >
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Previous page"
        title="Previous page"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft aria-hidden="true" />
      </Button>
      {pageList(page, totalPages).map((value, index) =>
        value === "ellipsis" ? (
          <span
            key={`ellipsis-${index}`}
            aria-hidden="true"
            className="px-1.5 text-xs text-muted-foreground"
          >
            …
          </span>
        ) : (
          <Button
            key={value}
            type="button"
            variant={value === page ? "default" : "outline"}
            size="icon-sm"
            aria-label={`Page ${value}`}
            aria-current={value === page ? "page" : undefined}
            onClick={() => onPageChange(value)}
          >
            {value}
          </Button>
        ),
      )}
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Next page"
        title="Next page"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        <ChevronRight aria-hidden="true" />
      </Button>
    </nav>
  );
}
