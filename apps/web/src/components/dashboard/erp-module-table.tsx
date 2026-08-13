"use client";

import { useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";

import { DataTable, DataTableLoading } from "@/components/dashboard/data-table";
import type { TablePayload } from "@/lib/mock/erp";

/**
 * Fetches a sub-module's table payload from the ERP stub API and renders it.
 * Each ERP sub-module page is a thin server component that mounts this.
 */
export function ErpModuleTable({ module }: { module: string }) {
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/v1/erp/${module}`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("failed"))))
      .then((body) => {
        if (!cancelled) setPayload(body.data as TablePayload);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [module]);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
        <AlertCircle aria-hidden="true" className="size-4 shrink-0 text-destructive" />
        Couldn&apos;t load {module} data.
      </div>
    );
  }

  if (!payload) return <DataTableLoading />;
  return <DataTable payload={payload} />;
}
