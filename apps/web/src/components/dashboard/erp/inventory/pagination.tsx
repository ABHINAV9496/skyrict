"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PaginationMeta } from "@/lib/api/inventory-api";

/** Prev/next pager driven by a list endpoint's PaginationMeta. */
export function Pagination({
    meta,
    onPageChange,
}: {
    meta: PaginationMeta;
    onPageChange: (page: number) => void;
}) {
    if (meta.totalPages <= 1) return null;

    return (
        <div className="flex items-center justify-between gap-3 border-t border-border/60 px-4 py-2.5">
            <p className="text-xs text-muted-foreground">
                {meta.total} item{meta.total === 1 ? "" : "s"} · page{" "}
                {meta.page} of {meta.totalPages}
            </p>
            <div className="flex items-center gap-1.5">
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onPageChange(meta.page - 1)}
                    disabled={meta.page <= 1}
                >
                    <ChevronLeft aria-hidden="true" />
                    Previous
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onPageChange(meta.page + 1)}
                    disabled={meta.page >= meta.totalPages}
                >
                    Next
                    <ChevronRight aria-hidden="true" />
                </Button>
            </div>
        </div>
    );
}
