"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellRing, PackagePlus } from "lucide-react";

import { AdjustStockDialog } from "@/components/dashboard/erp/inventory/adjust-dialog";
import { InventoryEmpty } from "@/components/dashboard/erp/inventory/inventory-empty";
import { InventoryError } from "@/components/dashboard/erp/inventory/inventory-banners";
import { Pagination } from "@/components/dashboard/erp/pagination";
import { DataTableSkeleton } from "@/components/dashboard/shared/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModuleAccess } from "@/lib/access/modules";
import { ApiError } from "@/lib/api/http";
import {
    getCatalogProducts,
    getCatalogWarehouses,
    listAlerts,
    type Alert,
    type PaginationMeta,
    type Product,
    type Warehouse,
} from "@/lib/api/inventory-api";

const PAGE_SIZE = 20;

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | {
          state: "ready";
          alerts: Alert[];
          meta: PaginationMeta;
          products: Product[];
          warehouses: Warehouse[];
      };

export function AlertsClient() {
    const { status: accessStatus, permissions } = useModuleAccess();
    const canAdjust =
        accessStatus === "ready" &&
        (permissions.includes("*") ||
            permissions.includes("erp.inventory.adjust"));
    const canApprove =
        accessStatus === "ready" &&
        (permissions.includes("*") ||
            permissions.includes("erp.inventory.adjust.approve") ||
            permissions.includes("erp.inventory.approve"));

    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [page, setPage] = useState(1);

    const [adjustOpen, setAdjustOpen] = useState(false);
    const [adjustPreset, setAdjustPreset] = useState<{
        productId: string;
        warehouseId: string;
    } | null>(null);

    const abortRef = useRef<AbortController | null>(null);

    const load = useCallback(async () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setStatus({ state: "loading" });
        try {
            const [result, products, warehouses] = await Promise.all([
                listAlerts(
                    { page, pageSize: PAGE_SIZE },
                    { signal: controller.signal },
                ),
                getCatalogProducts(),
                getCatalogWarehouses(),
            ]);
            if (controller.signal.aborted) return;
            setStatus({
                state: "ready",
                alerts: result.data,
                meta: result.meta,
                products,
                warehouses,
            });
        } catch (error) {
            if (controller.signal.aborted) return;
            const message =
                error instanceof ApiError
                    ? error.message
                    : "Could not load alerts.";
            setStatus({ state: "error", message });
        }
    }, [page]);

    useEffect(() => {
        void load();
        return () => abortRef.current?.abort();
    }, [load]);

    const warehouseById = useMemo(() => {
        const map = new Map<string, Warehouse>();
        if (status.state === "ready") {
            for (const warehouse of status.warehouses)
                map.set(warehouse.id, warehouse);
        }
        return map;
    }, [status]);

    if (status.state === "loading") return <DataTableSkeleton rows={6} />;

    if (status.state === "error") {
        return <InventoryError message={status.message} />;
    }

    const { alerts, meta, products, warehouses } = status;

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
                {meta.total} product{meta.total === 1 ? "" : "s"} at or below
                their reorder point
            </p>

            {alerts.length === 0 ? (
                <InventoryEmpty
                    title="No reorder alerts"
                    description="Nothing is at or below its reorder point right now."
                    icon={BellRing}
                />
            ) : (
                <div className="overflow-hidden rounded-xl border border-border bg-card">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="border-b border-border bg-muted/40">
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        SKU
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Product
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Warehouse
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        On hand
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Reorder at
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Status
                                    </th>
                                    {canAdjust && (
                                        <th scope="col" className="px-4 py-3">
                                            <span className="sr-only">
                                                Actions
                                            </span>
                                        </th>
                                    )}
                                </tr>
                            </thead>
                            <tbody>
                                {alerts.map((alert) => {
                                    const warehouse = warehouseById.get(
                                        alert.warehouseId,
                                    );
                                    const onHand = Number(alert.qtyOnHand);
                                    const reorder = Number(alert.reorderPoint);
                                    return (
                                        <tr
                                            key={`${alert.productId}-${alert.warehouseId}`}
                                            className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                                        >
                                            <td className="px-4 py-3 font-medium text-foreground">
                                                {alert.sku}
                                            </td>
                                            <td className="px-4 py-3 text-foreground">
                                                {alert.name}
                                            </td>
                                            <td className="px-4 py-3 text-muted-foreground">
                                                {warehouse?.name ??
                                                    "Unknown warehouse"}
                                            </td>
                                            <td className="px-4 py-3 text-right font-medium tabular-nums text-destructive">
                                                {alert.qtyOnHand}
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                                                {alert.reorderPoint}
                                            </td>
                                            <td className="px-4 py-3">
                                                {onHand < reorder ? (
                                                    <Badge
                                                        variant="outline"
                                                        className="bg-destructive/10 text-destructive ring-1 ring-destructive/30"
                                                    >
                                                        Below reorder
                                                    </Badge>
                                                ) : (
                                                    <Badge
                                                        variant="outline"
                                                        className="bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400"
                                                    >
                                                        At reorder
                                                    </Badge>
                                                )}
                                            </td>
                                            {canAdjust ? (
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center justify-end">
                                                        <Button
                                                            variant="ghost"
                                                            size="icon-sm"
                                                            onClick={() => {
                                                                setAdjustPreset(
                                                                    {
                                                                        productId:
                                                                            alert.productId,
                                                                        warehouseId:
                                                                            alert.warehouseId,
                                                                    },
                                                                );
                                                                setAdjustOpen(
                                                                    true,
                                                                );
                                                            }}
                                                            aria-label={`Adjust stock for ${alert.name}`}
                                                        >
                                                            <PackagePlus aria-hidden="true" />
                                                        </Button>
                                                    </div>
                                                </td>
                                            ) : null}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                    <Pagination meta={meta} onPageChange={setPage} />
                </div>
            )}

            <AdjustStockDialog
                open={adjustOpen}
                onOpenChange={setAdjustOpen}
                onAdjusted={() => void load()}
                products={products}
                warehouses={warehouses}
                defaultProductId={adjustPreset?.productId}
                defaultWarehouseId={adjustPreset?.warehouseId}
                canApprove={canApprove}
            />
        </div>
    );
}
