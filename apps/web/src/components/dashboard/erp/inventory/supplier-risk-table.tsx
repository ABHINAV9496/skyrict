"use client";

import { Spinner } from "@/components/ui/spinner";
import { useCallback, useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { InventoryEmpty } from "@/components/dashboard/erp/inventory/inventory-empty";
import { ApiError } from "@/lib/api/http";
import {
  listSupplierRisk,
  type SupplierRiskBand,
  type SupplierRiskItem,
} from "@/lib/api/ai-api";
import { listSuppliers, type Supplier } from "@/lib/api/inventory-api";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; rows: Row[]; counts: Record<string, number> };

interface Row {
  supplier: Supplier;
  risk: SupplierRiskItem | null;
}

const BAND_STYLES: Record<SupplierRiskBand, string> = {
  low: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/30",
  medium: "bg-amber-500/10 text-amber-700 ring-amber-500/30",
  high: "bg-red-500/10 text-red-700 ring-red-500/30",
};

const BAND_LABELS: Record<SupplierRiskBand, string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
};

export function SupplierRiskTable() {
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [filter, setFilter] = useState<"all" | SupplierRiskBand>("all");

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [suppliersRes, riskRes] = await Promise.all([
        listSuppliers({ page: 1, pageSize: 100 }),
        listSupplierRisk(),
      ]);
      const riskBySupplier = new Map(
        riskRes.data.map((item) => [item.supplier_id, item]),
      );
      const rows: Row[] = suppliersRes.data.map((supplier) => ({
        supplier,
        risk: riskBySupplier.get(supplier.id) ?? null,
      }));
      const counts: Record<string, number> = { low: 0, medium: 0, high: 0 };
      for (const row of rows) {
        if (row.risk) counts[row.risk.risk_band] += 1;
      }
      setStatus({ state: "ready", rows, counts });
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "Could not load suppliers.";
      setStatus({ state: "error", message: msg });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    );
  }

  if (status.state === "error") {
    return <p className="text-sm text-destructive py-8 text-center">{status.message}</p>;
  }

  const { rows, counts } = status;
  const filtered = filter === "all" ? rows : rows.filter((r) => r.risk?.risk_band === filter);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
          Supplier risk
        </h2>
        <div className="flex gap-1.5">
          {(["all", "low", "medium", "high"] as const).map((b) => (
            <button
              key={b}
              onClick={() => setFilter(b)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === b
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              {b === "all" ? "All" : BAND_LABELS[b]}
              {b !== "all" && (
                <span className="opacity-70">{counts[b]}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <InventoryEmpty
          title="No suppliers"
          description="No suppliers were found. Suppliers unlock the risk-adjusted restock model."
          icon={ShieldAlert}
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40">
                  <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                    Supplier
                  </th>
                  <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                    Contact
                  </th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                    Lead time
                  </th>
                  <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                    Risk
                  </th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                    Score
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr
                    key={row.supplier.id}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                  >
                    <td className="px-4 py-3 font-medium text-foreground">
                      {row.supplier.name}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {row.supplier.contactName || row.supplier.contactEmail || "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-foreground">
                      {row.supplier.leadTimeDays} d
                    </td>
                    <td className="px-4 py-3">
                      {row.risk ? (
                        <Badge
                          variant="outline"
                          className={`text-xs ring-1 ${BAND_STYLES[row.risk.risk_band] ?? ""}`}
                          title={row.risk.reason}
                        >
                          {BAND_LABELS[row.risk.risk_band]}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          Not graded
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                      {row.risk ? Number(row.risk.score).toFixed(3) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}