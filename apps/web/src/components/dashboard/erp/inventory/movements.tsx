"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeftRight } from "lucide-react";

import { InventoryEmpty } from "@/components/dashboard/erp/inventory/inventory-empty";
import { InventoryError } from "@/components/dashboard/erp/inventory/inventory-banners";
import { Pagination } from "@/components/dashboard/erp/pagination";
import { DataTableSkeleton } from "@/components/dashboard/shared/data-table";
import { Badge } from "@/components/ui/badge";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/http";
import {
    formatDate,
    getCatalogProducts,
    getCatalogWarehouses,
    listMovements,
    movementTypeLabel,
    type PaginationMeta,
    type Product,
    type StockMovement,
    type Warehouse,
} from "@/lib/api/inventory-api";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

const MOVEMENT_BADGE_CLASS: Record<string, string> = {
    receipt:
        "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
    issue: "bg-orange-500/15 text-orange-700 ring-1 ring-orange-500/30 dark:text-orange-400",
    transfer:
        "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
    adjustment:
        "bg-violet-500/15 text-violet-700 ring-1 ring-violet-500/30 dark:text-violet-400",
    reservation:
        "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
    release:
        "bg-slate-500/15 text-slate-700 ring-1 ring-slate-500/30 dark:text-slate-400",
};

const TYPE_OPTIONS = [
    "receipt",
    "issue",
    "transfer",
    "adjustment",
    "reservation",
    "release",
];

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | {
          state: "ready";
          movements: StockMovement[];
          meta: PaginationMeta;
          products: Product[];
          warehouses: Warehouse[];
      };

export function MovementsClient() {
    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [page, setPage] = useState(1);
    const [movementType, setMovementType] = useState<string>("");

    const abortRef = useRef<AbortController | null>(null);

    const load = useCallback(async () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setStatus({ state: "loading" });
        try {
            const [result, products, warehouses] = await Promise.all([
                listMovements(
                    {
                        page,
                        pageSize: PAGE_SIZE,
                        movementType: movementType || undefined,
                    },
                    { signal: controller.signal },
                ),
                getCatalogProducts(),
                getCatalogWarehouses(),
            ]);
            if (controller.signal.aborted) return;
            setStatus({
                state: "ready",
                movements: result.data,
                meta: result.meta,
                products,
                warehouses,
            });
        } catch (error) {
            if (controller.signal.aborted) return;
            const message =
                error instanceof ApiError
                    ? error.message
                    : "Could not load movements.";
            setStatus({ state: "error", message });
        }
    }, [page, movementType]);

    useEffect(() => {
        setPage(1);
    }, [movementType]);

    useEffect(() => {
        void load();
        return () => abortRef.current?.abort();
    }, [load]);

    const productById = useMemo(() => {
        const map = new Map<string, Product>();
        if (status.state === "ready") {
            for (const product of status.products) map.set(product.id, product);
        }
        return map;
    }, [status]);

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

    const { movements, meta } = status;

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">
                    {meta.total} movement{meta.total === 1 ? "" : "s"}
                </p>
                <div className="w-44">
                    <Select
                        value={movementType || "__all__"}
                        onValueChange={(value) =>
                            setMovementType(value === "__all__" ? "" : value)
                        }
                    >
                        <SelectTrigger className="w-full">
                            <SelectValue placeholder="All types" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">All types</SelectItem>
                            {TYPE_OPTIONS.map((type) => (
                                <SelectItem key={type} value={type}>
                                    {movementTypeLabel(type)}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {movements.length === 0 ? (
                <InventoryEmpty
                    title="No movements yet"
                    description="Every stock change is recorded here as an immutable ledger entry."
                    icon={ArrowLeftRight}
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
                                        Date
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
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Type
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Qty
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Reference
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {movements.map((movement) => {
                                    const product = productById.get(
                                        movement.productId,
                                    );
                                    const warehouse = warehouseById.get(
                                        movement.warehouseId,
                                    );
                                    const qtyNumber = Number(movement.qty);
                                    return (
                                        <tr
                                            key={movement.id}
                                            className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                                        >
                                            <td className="px-4 py-3 text-muted-foreground">
                                                {formatDate(movement.createdAt)}
                                            </td>
                                            <td className="px-4 py-3">
                                                <p className="font-medium text-foreground">
                                                    {product?.name ??
                                                        "Unknown product"}
                                                </p>
                                                <p className="text-xs text-muted-foreground">
                                                    {product?.sku ??
                                                        movement.productId}
                                                </p>
                                            </td>
                                            <td className="px-4 py-3 text-muted-foreground">
                                                {warehouse?.name ??
                                                    "Unknown warehouse"}
                                            </td>
                                            <td className="px-4 py-3">
                                                <Badge
                                                    variant="outline"
                                                    className={
                                                        MOVEMENT_BADGE_CLASS[
                                                            movement
                                                                .movementType
                                                        ] ?? ""
                                                    }
                                                >
                                                    {movementTypeLabel(
                                                        movement.movementType,
                                                    )}
                                                </Badge>
                                            </td>
                                            <td
                                                className={cn(
                                                    "px-4 py-3 text-right font-medium tabular-nums",
                                                    qtyNumber < 0
                                                        ? "text-red-600 dark:text-red-400"
                                                        : "text-emerald-600 dark:text-emerald-400",
                                                )}
                                            >
                                                {qtyNumber > 0 ? "+" : ""}
                                                {movement.qty}
                                            </td>
                                            <td className="px-4 py-3 text-muted-foreground">
                                                {movement.refType ? (
                                                    <span className="font-mono text-xs">
                                                        {movement.refType}
                                                    </span>
                                                ) : (
                                                    "—"
                                                )}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                    <Pagination meta={meta} onPageChange={setPage} />
                </div>
            )}
        </div>
    );
}
