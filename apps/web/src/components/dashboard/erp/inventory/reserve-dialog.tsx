"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

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
    reserveStock,
    type Product,
    type Warehouse,
} from "@/lib/api/inventory-api";

export function ReserveStockDialog({
    open,
    onOpenChange,
    onReserved,
    products,
    warehouses,
    defaultProductId,
    defaultWarehouseId,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onReserved: () => void;
    products: Product[];
    warehouses: Warehouse[];
    defaultProductId?: string;
    defaultWarehouseId?: string;
}) {
    const [productId, setProductId] = useState("");
    const [warehouseId, setWarehouseId] = useState("");
    const [qty, setQty] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (open) {
            setProductId(defaultProductId ?? "");
            setWarehouseId(defaultWarehouseId ?? "");
            setQty("");
            setError(null);
            setSubmitting(false);
        }
    }, [open, defaultProductId, defaultWarehouseId]);

    const qtyNumber = Number(qty);

    const activeProducts = products.filter((product) => product.isActive);
    const activeWarehouses = warehouses.filter(
        (warehouse) => warehouse.isActive,
    );

    async function handleSubmit(event: FormEvent) {
        event.preventDefault();
        if (!productId || !warehouseId) {
            setError("Select a product and a warehouse.");
            return;
        }
        if (!Number.isFinite(qtyNumber) || qtyNumber <= 0) {
            setError("Enter a quantity greater than zero.");
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await reserveStock({
                productId,
                warehouseId,
                qty: qtyNumber,
            });
            onReserved();
            onOpenChange(false);
        } catch (submitError) {
            const message =
                submitError instanceof ApiError
                    ? submitError.message
                    : "Could not reserve stock.";
            setError(message);
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Reserve stock</DialogTitle>
                    <DialogDescription>
                        Holds stock for a pending order. Reserved stock is
                        unavailable for other orders until released.
                    </DialogDescription>
                </DialogHeader>

                <form
                    id="inventory-reserve"
                    onSubmit={handleSubmit}
                    className="grid gap-3"
                >
                    {error ? <InventoryError message={error} /> : null}
                    <div className="grid gap-1.5">
                        <Label htmlFor="reserve-product">Product</Label>
                        <Select value={productId} onValueChange={setProductId}>
                            <SelectTrigger
                                id="reserve-product"
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
                    <div className="grid gap-1.5">
                        <Label htmlFor="reserve-warehouse">Warehouse</Label>
                        <Select
                            value={warehouseId}
                            onValueChange={setWarehouseId}
                        >
                            <SelectTrigger
                                id="reserve-warehouse"
                                className="w-full"
                            >
                                <SelectValue placeholder="Select a warehouse" />
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
                        <Label htmlFor="reserve-qty">Quantity</Label>
                        <Input
                            id="reserve-qty"
                            type="number"
                            step="1"
                            min="1"
                            value={qty}
                            onChange={(event) => setQty(event.target.value)}
                            placeholder="e.g. 10"
                            required
                        />
                    </div>
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
                        form="inventory-reserve"
                        disabled={submitting || !productId || !warehouseId}
                    >
                        {submitting ? "Reserving…" : "Reserve stock"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
