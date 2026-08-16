"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ShieldAlert } from "lucide-react";

import { InventoryError } from "@/components/dashboard/erp/inventory/inventory-banners";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/http";
import {
    ADJUST_APPROVE_THRESHOLD,
    adjustStock,
    type Product,
    type Warehouse,
} from "@/lib/api/inventory-api";

export function AdjustStockDialog({
    open,
    onOpenChange,
    onAdjusted,
    products,
    warehouses,
    defaultProductId,
    defaultWarehouseId,
    canApprove,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onAdjusted: () => void;
    products: Product[];
    warehouses: Warehouse[];
    defaultProductId?: string;
    defaultWarehouseId?: string;
    canApprove: boolean;
}) {
    const [productId, setProductId] = useState("");
    const [warehouseId, setWarehouseId] = useState("");
    const [qty, setQty] = useState("");
    const [reason, setReason] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (open) {
            setProductId(defaultProductId ?? "");
            setWarehouseId(defaultWarehouseId ?? "");
            setQty("");
            setReason("");
            setError(null);
            setSubmitting(false);
        }
    }, [open, defaultProductId, defaultWarehouseId]);

    const qtyNumber = Number(qty);
    const requiresApproval =
        Number.isFinite(qtyNumber) &&
        Math.abs(qtyNumber) > ADJUST_APPROVE_THRESHOLD;
    const blocked = requiresApproval && !canApprove;

    async function handleSubmit(event: FormEvent) {
        event.preventDefault();
        if (!productId || !warehouseId) {
            setError("Select a product and a warehouse.");
            return;
        }
        if (!Number.isFinite(qtyNumber) || qtyNumber === 0) {
            setError(
                "Enter a non-zero signed quantity (+ receives, − issues).",
            );
            return;
        }
        if (!reason.trim()) {
            setError("A reason is required for adjustments.");
            return;
        }
        if (requiresApproval && !canApprove) {
            setError(
                `This adjustment exceeds the ${ADJUST_APPROVE_THRESHOLD} unit approval threshold and requires erp.inventory.adjust.approve.`,
            );
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await adjustStock({
                productId,
                warehouseId,
                qty: qtyNumber,
                reason: reason.trim(),
            });
            onAdjusted();
            onOpenChange(false);
        } catch (submitError) {
            const message =
                submitError instanceof ApiError
                    ? submitError.message
                    : "Could not adjust stock.";
            setError(message);
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Adjust stock</DialogTitle>
                    <DialogDescription>
                        Records a signed movement: positive receives, negative
                        issues.
                    </DialogDescription>
                </DialogHeader>

                <form
                    id="inventory-adjust"
                    onSubmit={handleSubmit}
                    className="grid gap-3"
                >
                    {error ? <InventoryError message={error} /> : null}
                    <div className="grid gap-1.5">
                        <Label htmlFor="adjust-product">Product</Label>
                        <Select value={productId} onValueChange={setProductId}>
                            <SelectTrigger
                                id="adjust-product"
                                className="w-full"
                            >
                                <SelectValue placeholder="Select a product" />
                            </SelectTrigger>
                            <SelectContent>
                                {products.map((product) => (
                                    <SelectItem
                                        key={product.id}
                                        value={product.id}
                                    >
                                        {product.sku} — {product.name}
                                        {product.isActive === false
                                            ? " (archived)"
                                            : ""}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="adjust-warehouse">Warehouse</Label>
                        <Select
                            value={warehouseId}
                            onValueChange={setWarehouseId}
                        >
                            <SelectTrigger
                                id="adjust-warehouse"
                                className="w-full"
                            >
                                <SelectValue placeholder="Select a warehouse" />
                            </SelectTrigger>
                            <SelectContent>
                                {warehouses.map((warehouse) => (
                                    <SelectItem
                                        key={warehouse.id}
                                        value={warehouse.id}
                                    >
                                        {warehouse.name}
                                        {warehouse.isActive === false
                                            ? " (archived)"
                                            : ""}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="adjust-qty">Quantity</Label>
                        <Input
                            id="adjust-qty"
                            type="number"
                            step="1"
                            value={qty}
                            onChange={(event) => setQty(event.target.value)}
                            placeholder="e.g. 25 or -10"
                            required
                        />
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="adjust-reason">Reason</Label>
                        <Input
                            id="adjust-reason"
                            value={reason}
                            onChange={(event) => setReason(event.target.value)}
                            placeholder="e.g. Cycle count discrepancy"
                            required
                            maxLength={255}
                        />
                    </div>

                    {requiresApproval ? (
                        <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-400">
                            <ShieldAlert
                                aria-hidden="true"
                                className="mt-0.5 size-4 shrink-0"
                            />
                            <div className="space-y-0.5">
                                <p className="font-medium">Approval required</p>
                                <p className="leading-relaxed">
                                    This adjustment exceeds the{" "}
                                    {ADJUST_APPROVE_THRESHOLD} unit threshold.{" "}
                                    {canApprove
                                        ? "You hold erp.inventory.adjust.approve, so submitting will post it."
                                        : "Only an account with erp.inventory.adjust.approve can post it."}
                                </p>
                            </div>
                        </div>
                    ) : null}
                </form>

                <DialogFooter showCloseButton={false}>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        disabled={submitting}
                    >
                        Cancel
                    </Button>
                    <Button
                        type="submit"
                        form="inventory-adjust"
                        disabled={
                            submitting || blocked || !productId || !warehouseId
                        }
                    >
                        {submitting
                            ? "Posting…"
                            : blocked
                              ? "Requires approval"
                              : "Post adjustment"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
