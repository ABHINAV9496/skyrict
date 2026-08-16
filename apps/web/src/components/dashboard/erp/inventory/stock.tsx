"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeftRight, Layers, PackagePlus } from "lucide-react";

import { AdjustStockDialog } from "@/components/dashboard/erp/inventory/adjust-dialog";
import { InventoryEmpty } from "@/components/dashboard/erp/inventory/inventory-empty";
import {
    InventoryError,
    InventorySuccess,
} from "@/components/dashboard/erp/inventory/inventory-banners";
import { Pagination } from "@/components/dashboard/erp/pagination";
import { TransferStockDialog } from "@/components/dashboard/erp/inventory/transfer-dialog";
import { DataTableSkeleton } from "@/components/dashboard/shared/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModuleAccess } from "@/lib/access/modules";
import { ApiError } from "@/lib/api/http";
import {
    getCatalogProducts,
    getCatalogWarehouses,
    listStockLevels,
    type PaginationMeta,
    type Product,
    type StockLevel,
    type Warehouse,
} from "@/lib/api/inventory-api";

const PAGE_SIZE = 20;

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | {
          state: "ready";
          levels: StockLevel[];
          meta: PaginationMeta;
          products: Product[];
          warehouses: Warehouse[];
      };

function levelStatus(level: StockLevel, product: Product | undefined) {
    const onHand = Number(level.qtyOnHand);
    const reorder = Number(product?.reorderPoint ?? 0);
    if (onHand <= reorder) return "low";
    return "ok";
}

export function StockClient() {
    const { status: accessStatus, permissions } = useModuleAccess();
    const canWrite =
        accessStatus === "ready" &&
        (permissions.includes("*") ||
            permissions.includes("erp.inventory.write"));
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
    const [notice, setNotice] = useState<string | null>(null);

    const [adjustOpen, setAdjustOpen] = useState(false);
    const [adjustPreset, setAdjustPreset] = useState<{
        productId: string;
        warehouseId: string;
    } | null>(null);
    const [transferOpen, setTransferOpen] = useState(false);
    const [transferPreset, setTransferPreset] = useState<{
        productId: string;
        fromWarehouseId: string;
    } | null>(null);

    const abortRef = useRef<AbortController | null>(null);

    const load = useCallback(async () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setStatus({ state: "loading" });
        try {
            const [result, products, warehouses] = await Promise.all([
                listStockLevels(
                    { page, pageSize: PAGE_SIZE },
                    { signal: controller.signal },
                ),
                getCatalogProducts(),
                getCatalogWarehouses(),
            ]);
            if (controller.signal.aborted) return;
            setStatus({
                state: "ready",
                levels: result.data,
                meta: result.meta,
                products,
                warehouses,
            });
        } catch (error) {
            if (controller.signal.aborted) return;
            const message =
                error instanceof ApiError
                    ? error.message
                    : "Could not load stock levels.";
            setStatus({ state: "error", message });
        }
    }, [page]);

    useEffect(() => {
        void load();
        return () => abortRef.current?.abort();
    }, [load]);

    useEffect(() => {
        if (!notice) return;
        const timer = setTimeout(() => setNotice(null), 4000);
        return () => clearTimeout(timer);
    }, [notice]);

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

    function openAdjust(preset?: { productId: string; warehouseId: string }) {
        setAdjustPreset(preset ?? null);
        setAdjustOpen(true);
    }

    function openTransfer(preset?: {
        productId: string;
        fromWarehouseId: string;
    }) {
        setTransferPreset(preset ?? null);
        setTransferOpen(true);
    }

    if (status.state === "loading") return <DataTableSkeleton rows={6} />;

    if (status.state === "error") {
        return <InventoryError message={status.message} />;
    }

    const { levels, meta, products, warehouses } = status;

    return (
        <div className="space-y-4">
            {notice ? <InventorySuccess message={notice} /> : null}

            <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">
                    {meta.total} stock level{meta.total === 1 ? "" : "s"} across{" "}
                    {warehouses.length} warehouse
                    {warehouses.length === 1 ? "" : "s"}
                </p>
                <div className="flex items-center gap-2">
                    {canAdjust ? (
                        <Button variant="outline" onClick={() => openAdjust()}>
                            <PackagePlus aria-hidden="true" />
                            Adjust stock
                        </Button>
                    ) : null}
                    {canWrite ? (
                        <Button onClick={() => openTransfer()}>
                            <ArrowLeftRight aria-hidden="true" />
                            Transfer stock
                        </Button>
                    ) : null}
                </div>
            </div>

            {levels.length === 0 ? (
                <InventoryEmpty
                    title="No stock levels yet"
                    description="Stock levels appear once a product has a movement in a warehouse — adjust or transfer to get started."
                    icon={Layers}
                    action={
                        canAdjust ? (
                            <Button onClick={() => openAdjust()}>
                                <PackagePlus aria-hidden="true" />
                                Adjust stock
                            </Button>
                        ) : undefined
                    }
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
                                        Reserved
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Available
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
                                    {(canAdjust || canWrite) && (
                                        <th scope="col" className="px-4 py-3">
                                            <span className="sr-only">
                                                Actions
                                            </span>
                                        </th>
                                    )}
                                </tr>
                            </thead>
                            <tbody>
                                {levels.map((level) => {
                                    const product = productById.get(
                                        level.productId,
                                    );
                                    const warehouse = warehouseById.get(
                                        level.warehouseId,
                                    );
                                    const statusFlag = levelStatus(
                                        level,
                                        product,
                                    );
                                    const onHand = Number(level.qtyOnHand);
                                    const reserved = Number(level.qtyReserved);
                                    const archived =
                                        product?.isActive === false ||
                                        warehouse?.isActive === false;
                                    return (
                                        <tr
                                            key={level.id}
                                            className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                                        >
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-2">
                                                    <p className="font-medium text-foreground">
                                                        {product?.name ??
                                                            "Unknown product"}
                                                    </p>
                                                    {product?.isActive ===
                                                    false ? (
                                                        <Badge
                                                            variant="outline"
                                                            className="text-muted-foreground"
                                                        >
                                                            archived
                                                        </Badge>
                                                    ) : null}
                                                </div>
                                                <p className="text-xs text-muted-foreground">
                                                    {product?.sku ??
                                                        level.productId}
                                                </p>
                                            </td>
                                            <td className="px-4 py-3 text-muted-foreground">
                                                <div className="flex items-center gap-2">
                                                    <span>
                                                        {warehouse?.name ??
                                                            "Unknown warehouse"}
                                                    </span>
                                                    {warehouse?.isActive ===
                                                    false ? (
                                                        <Badge
                                                            variant="outline"
                                                            className="text-muted-foreground"
                                                        >
                                                            archived
                                                        </Badge>
                                                    ) : null}
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-foreground">
                                                {level.qtyOnHand}
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                                                {level.qtyReserved}
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-foreground">
                                                {onHand - reserved}
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                                                {product?.reorderPoint ?? "—"}
                                            </td>
                                            <td className="px-4 py-3">
                                                {statusFlag === "low" ? (
                                                    <Badge
                                                        variant="outline"
                                                        className="bg-destructive/10 text-destructive ring-1 ring-destructive/30"
                                                    >
                                                        Low stock
                                                    </Badge>
                                                ) : (
                                                    <Badge
                                                        variant="outline"
                                                        className="bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400"
                                                    >
                                                        In stock
                                                    </Badge>
                                                )}
                                            </td>
                                            {canAdjust || canWrite ? (
                                                <td className="px-4 py-3">
                                                    <div className="flex items-center justify-end gap-1.5">
                                                        {canAdjust ? (
                                                            <Button
                                                                variant="ghost"
                                                                size="icon-sm"
                                                                onClick={() =>
                                                                    openAdjust({
                                                                        productId:
                                                                            level.productId,
                                                                        warehouseId:
                                                                            level.warehouseId,
                                                                    })
                                                                }
                                                                aria-label={`Adjust stock for ${product?.name ?? level.productId} at ${warehouse?.name ?? "unknown warehouse"}`}
                                                            >
                                                                <PackagePlus aria-hidden="true" />
                                                            </Button>
                                                        ) : null}
                                                        {canWrite ? (
                                                            <Button
                                                                variant="ghost"
                                                                size="icon-sm"
                                                                disabled={
                                                                    archived
                                                                }
                                                                onClick={() =>
                                                                    openTransfer(
                                                                        {
                                                                            productId:
                                                                                level.productId,
                                                                            fromWarehouseId:
                                                                                level.warehouseId,
                                                                        },
                                                                    )
                                                                }
                                                                aria-label={`Transfer stock for ${product?.name ?? level.productId} from ${warehouse?.name ?? "unknown warehouse"}`}
                                                            >
                                                                <ArrowLeftRight aria-hidden="true" />
                                                            </Button>
                                                        ) : null}
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
                onAdjusted={() => {
                    setNotice("Stock adjusted.");
                    void load();
                }}
                products={products}
                warehouses={warehouses}
                defaultProductId={adjustPreset?.productId}
                defaultWarehouseId={adjustPreset?.warehouseId}
                canApprove={canApprove}
            />

            <TransferStockDialog
                open={transferOpen}
                onOpenChange={setTransferOpen}
                onTransferred={() => {
                    setNotice("Stock transferred.");
                    void load();
                }}
                products={products}
                warehouses={warehouses}
                defaultProductId={transferPreset?.productId}
                defaultFromWarehouseId={transferPreset?.fromWarehouseId}
            />
        </div>
    );
}
