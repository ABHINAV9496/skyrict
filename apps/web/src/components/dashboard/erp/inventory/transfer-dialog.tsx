"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { TriangleAlert } from "lucide-react";

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
    transferStock,
    type Product,
    type Warehouse,
} from "@/lib/api/inventory-api";

export function TransferStockDialog({
    open,
    onOpenChange,
    onTransferred,
    products,
    warehouses,
    defaultProductId,
    defaultFromWarehouseId,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onTransferred: () => void;
    products: Product[];
    warehouses: Warehouse[];
    defaultProductId?: string;
    defaultFromWarehouseId?: string;
}) {
    const [productId, setProductId] = useState("");
    const [fromWarehouseId, setFromWarehouseId] = useState("");
    const [toWarehouseId, setToWarehouseId] = useState("");
    const [qty, setQty] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (open) {
            setProductId(defaultProductId ?? "");
            setFromWarehouseId(defaultFromWarehouseId ?? "");
            setToWarehouseId("");
            setQty("");
            setError(null);
            setSubmitting(false);
        }
    }, [open, defaultProductId, defaultFromWarehouseId]);

    const qtyNumber = Number(qty);
    const sameWarehouse =
        Boolean(fromWarehouseId) && fromWarehouseId === toWarehouseId;

    // Posting block: archived products/warehouses cannot be moved.
    const activeProducts = products.filter((product) => product.isActive);
    const activeWarehouses = warehouses.filter(
        (warehouse) => warehouse.isActive,
    );

    async function handleSubmit(event: FormEvent) {
        event.preventDefault();
        if (!productId || !fromWarehouseId || !toWarehouseId) {
            setError("Select a product, source, and destination warehouse.");
            return;
        }
        if (sameWarehouse) {
            setError("Source and destination must be different warehouses.");
            return;
        }
        if (!Number.isFinite(qtyNumber) || qtyNumber <= 0) {
            setError("Enter a quantity greater than zero.");
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await transferStock({
                productId,
                fromWarehouseId,
                toWarehouseId,
                qty: qtyNumber,
            });
            onTransferred();
            onOpenChange(false);
        } catch (submitError) {
            const message =
                submitError instanceof ApiError
                    ? submitError.message
                    : "Could not transfer stock.";
            setError(message);
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Transfer stock</DialogTitle>
                    <DialogDescription>
                        Moves stock between two warehouses atomically.
                    </DialogDescription>
                </DialogHeader>

                <form
                    id="inventory-transfer"
                    onSubmit={handleSubmit}
                    className="grid gap-3"
                >
                    {error ? <InventoryError message={error} /> : null}
                    <div className="grid gap-1.5">
                        <Label htmlFor="transfer-product">Product</Label>
                        <Select value={productId} onValueChange={setProductId}>
                            <SelectTrigger
                                id="transfer-product"
                                className="w-full"
                            >
                                <SelectValue placeholder="Select a product" />
                            </SelectTrigger>
                            <SelectContent>
                                {activeProducts.map((product) => (
                                    <SelectItem
                                        key={product.id}
                                        value={product.id}
                                    >
                                        {product.sku} - {product.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="grid gap-1.5">
                            <Label htmlFor="transfer-from">From</Label>
                            <Select
                                value={fromWarehouseId}
                                onValueChange={setFromWarehouseId}
                            >
                                <SelectTrigger
                                    id="transfer-from"
                                    className="w-full"
                                >
                                    <SelectValue placeholder="Source" />
                                </SelectTrigger>
                                <SelectContent>
                                    {activeWarehouses.map((warehouse) => (
                                        <SelectItem
                                            key={warehouse.id}
                                            value={warehouse.id}
                                        >
                                            {warehouse.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="grid gap-1.5">
                            <Label htmlFor="transfer-to">To</Label>
                            <Select
                                value={toWarehouseId}
                                onValueChange={setToWarehouseId}
                            >
                                <SelectTrigger
                                    id="transfer-to"
                                    className="w-full"
                                >
                                    <SelectValue placeholder="Destination" />
                                </SelectTrigger>
                                <SelectContent>
                                    {activeWarehouses.map((warehouse) => (
                                        <SelectItem
                                            key={warehouse.id}
                                            value={warehouse.id}
                                        >
                                            {warehouse.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="transfer-qty">Quantity</Label>
                        <Input
                            id="transfer-qty"
                            type="number"
                            min="1"
                            step="1"
                            value={qty}
                            onChange={(event) => setQty(event.target.value)}
                            placeholder="e.g. 40"
                            required
                        />
                    </div>

                    {sameWarehouse ? (
                        <div className="flex items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                            <TriangleAlert
                                aria-hidden="true"
                                className="mt-0.5 size-4 shrink-0"
                            />
                            <p>
                                Source and destination must be different
                                warehouses.
                            </p>
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
                        form="inventory-transfer"
                        disabled={
                            submitting ||
                            sameWarehouse ||
                            !productId ||
                            !fromWarehouseId ||
                            !toWarehouseId
                        }
                    >
                        {submitting ? "Transferring…" : "Transfer stock"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
