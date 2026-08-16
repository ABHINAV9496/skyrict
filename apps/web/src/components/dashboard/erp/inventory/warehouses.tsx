"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
    Pencil,
    Plus,
    RotateCcw,
    Trash2,
    Warehouse as WarehouseIcon,
} from "lucide-react";

import { InventoryEmpty } from "@/components/dashboard/erp/inventory/inventory-empty";
import {
    InventoryError,
    InventorySuccess,
} from "@/components/dashboard/erp/inventory/inventory-banners";
import { Pagination } from "@/components/dashboard/erp/inventory/pagination";
import { DataTableSkeleton } from "@/components/dashboard/shared/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useModuleAccess } from "@/lib/access/modules";
import { ApiError } from "@/lib/api/http";
import {
    createWarehouse,
    deleteWarehouse,
    formatDate,
    listWarehouses,
    reactivateWarehouse,
    updateWarehouse,
    type PaginationMeta,
    type Warehouse,
} from "@/lib/api/inventory-api";

const PAGE_SIZE = 20;

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; warehouses: Warehouse[]; meta: PaginationMeta };

const EMPTY_FORM = { name: "", location: "" };

function formFromWarehouse(warehouse: Warehouse) {
    return {
        name: warehouse.name,
        location: warehouse.location ?? "",
    };
}

export function WarehousesClient() {
    const { status: accessStatus, permissions } = useModuleAccess();
    const canWrite =
        accessStatus === "ready" &&
        (permissions.includes("*") ||
            permissions.includes("erp.inventory.write"));

    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [page, setPage] = useState(1);
    const [includeInactive, setIncludeInactive] = useState(false);
    const [notice, setNotice] = useState<string | null>(null);

    const [dialogOpen, setDialogOpen] = useState(false);
    const [editing, setEditing] = useState<Warehouse | null>(null);
    const [form, setForm] = useState(EMPTY_FORM);
    const [submitting, setSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const [deleting, setDeleting] = useState<Warehouse | null>(null);
    const [deletingBusy, setDeletingBusy] = useState(false);
    const [deleteError, setDeleteError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const result = await listWarehouses({
                page,
                pageSize: PAGE_SIZE,
                includeInactive,
            });
            setStatus({
                state: "ready",
                warehouses: result.data,
                meta: result.meta,
            });
        } catch (error) {
            const message =
                error instanceof ApiError
                    ? error.message
                    : "Could not load warehouses.";
            setStatus({ state: "error", message });
        }
    }, [page, includeInactive]);

    useEffect(() => {
        void load();
    }, [load]);

    useEffect(() => {
        if (!notice) return;
        const timer = setTimeout(() => setNotice(null), 4000);
        return () => clearTimeout(timer);
    }, [notice]);

    function openCreate() {
        setEditing(null);
        setForm(EMPTY_FORM);
        setFormError(null);
        setDialogOpen(true);
    }

    function openEdit(warehouse: Warehouse) {
        setEditing(warehouse);
        setForm(formFromWarehouse(warehouse));
        setFormError(null);
        setDialogOpen(true);
    }

    async function handleSubmit(event: FormEvent) {
        event.preventDefault();
        const name = form.name.trim();
        if (!name) {
            setFormError("Warehouse name is required.");
            return;
        }
        setSubmitting(true);
        setFormError(null);
        try {
            const input = {
                name,
                location: form.location.trim() || null,
            };
            if (editing) {
                await updateWarehouse(editing.id, input);
                setNotice(`Updated warehouse ${name}.`);
            } else {
                await createWarehouse(input);
                setNotice(`Created warehouse ${name}.`);
            }
            setDialogOpen(false);
            if (page !== 1) setPage(1);
            else void load();
        } catch (error) {
            const message =
                error instanceof ApiError
                    ? error.message
                    : editing
                      ? "Could not update the warehouse."
                      : "Could not create the warehouse.";
            setFormError(message);
        } finally {
            setSubmitting(false);
        }
    }

    async function handleDelete() {
        if (!deleting) return;
        setDeletingBusy(true);
        setDeleteError(null);
        try {
            await deleteWarehouse(deleting.id);
            setNotice(`Archived warehouse ${deleting.name}.`);
            setDeleting(null);
            if (page !== 1) setPage(1);
            else void load();
        } catch (error) {
            const message =
                error instanceof ApiError
                    ? error.message
                    : "Could not delete the warehouse.";
            setDeleteError(message);
        } finally {
            setDeletingBusy(false);
        }
    }

    async function handleReactivate(warehouse: Warehouse) {
        try {
            await reactivateWarehouse(warehouse.id);
            setNotice(`Reactivated warehouse ${warehouse.name}.`);
            if (page !== 1) setPage(1);
            else void load();
        } catch (error) {
            const message =
                error instanceof ApiError
                    ? error.message
                    : "Could not reactivate the warehouse.";
            setNotice(message);
        }
    }

    if (status.state === "loading") return <DataTableSkeleton rows={6} />;

    if (status.state === "error") {
        return <InventoryError message={status.message} />;
    }

    return (
        <div className="space-y-4">
            {notice ? <InventorySuccess message={notice} /> : null}

            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-4">
                    <p className="text-sm text-muted-foreground">
                        {status.meta.total} warehouse
                        {status.meta.total === 1 ? "" : "s"}
                    </p>
                    <div className="flex items-center gap-2">
                        <Checkbox
                            id="warehouses-include-archived"
                            checked={includeInactive}
                            onCheckedChange={(checked) => {
                                if (page !== 1) setPage(1);
                                setIncludeInactive(checked === true);
                            }}
                            aria-label="Include archived warehouses"
                        />
                        <label
                            htmlFor="warehouses-include-archived"
                            className="cursor-pointer text-sm text-muted-foreground"
                        >
                            Include archived
                        </label>
                    </div>
                </div>
                {canWrite ? (
                    <Button onClick={openCreate}>
                        <Plus aria-hidden="true" />
                        New warehouse
                    </Button>
                ) : null}
            </div>

            {status.warehouses.length === 0 ? (
                <InventoryEmpty
                    title="No warehouses yet"
                    description="Warehouses are where stock lives. Add one before moving stock around."
                    icon={WarehouseIcon}
                    action={
                        canWrite ? (
                            <Button onClick={openCreate}>
                                <Plus aria-hidden="true" />
                                Create a warehouse
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
                                        Name
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Location
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Status
                                    </th>
                                    <th
                                        scope="col"
                                        className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
                                    >
                                        Created
                                    </th>
                                    {canWrite ? (
                                        <th scope="col" className="px-4 py-3">
                                            <span className="sr-only">
                                                Actions
                                            </span>
                                        </th>
                                    ) : null}
                                </tr>
                            </thead>
                            <tbody>
                                {status.warehouses.map((warehouse) => (
                                    <tr
                                        key={warehouse.id}
                                        className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30"
                                    >
                                        <td className="px-4 py-3 font-medium text-foreground">
                                            {warehouse.name}
                                        </td>
                                        <td className="px-4 py-3 text-muted-foreground">
                                            {warehouse.location ?? "—"}
                                        </td>
                                        <td className="px-4 py-3">
                                            {warehouse.isActive ? (
                                                <Badge
                                                    variant="outline"
                                                    className="bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400"
                                                >
                                                    Active
                                                </Badge>
                                            ) : (
                                                <Badge
                                                    variant="outline"
                                                    className="text-muted-foreground"
                                                >
                                                    Archived
                                                </Badge>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-muted-foreground">
                                            {formatDate(warehouse.createdAt)}
                                        </td>
                                        {canWrite ? (
                                            <td className="px-4 py-3">
                                                <div className="flex items-center justify-end gap-1">
                                                    {warehouse.isActive ? (
                                                        <>
                                                            <Button
                                                                variant="ghost"
                                                                size="icon-sm"
                                                                onClick={() =>
                                                                    openEdit(
                                                                        warehouse,
                                                                    )
                                                                }
                                                                aria-label={`Edit ${warehouse.name}`}
                                                            >
                                                                <Pencil aria-hidden="true" />
                                                            </Button>
                                                            <Button
                                                                variant="ghost"
                                                                size="icon-sm"
                                                                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                                                                onClick={() => {
                                                                    setDeleteError(
                                                                        null,
                                                                    );
                                                                    setDeleting(
                                                                        warehouse,
                                                                    );
                                                                }}
                                                                aria-label={`Delete ${warehouse.name}`}
                                                            >
                                                                <Trash2 aria-hidden="true" />
                                                            </Button>
                                                        </>
                                                    ) : (
                                                        <Button
                                                            variant="ghost"
                                                            size="icon-sm"
                                                            onClick={() =>
                                                                void handleReactivate(
                                                                    warehouse,
                                                                )
                                                            }
                                                            aria-label={`Reactivate ${warehouse.name}`}
                                                        >
                                                            <RotateCcw aria-hidden="true" />
                                                        </Button>
                                                    )}
                                                </div>
                                            </td>
                                        ) : null}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <Pagination meta={status.meta} onPageChange={setPage} />
                </div>
            )}

            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>
                            {editing ? "Edit warehouse" : "New warehouse"}
                        </DialogTitle>
                        <DialogDescription>
                            Warehouse names must be unique in this workspace.
                        </DialogDescription>
                    </DialogHeader>

                    <form
                        id="inventory-warehouse-form"
                        onSubmit={handleSubmit}
                        className="grid gap-3"
                    >
                        {formError ? (
                            <InventoryError message={formError} />
                        ) : null}
                        <div className="grid gap-1.5">
                            <Label htmlFor="warehouse-name">Name</Label>
                            <Input
                                id="warehouse-name"
                                value={form.name}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        name: event.target.value,
                                    })
                                }
                                placeholder="e.g. East DC"
                                required
                                maxLength={100}
                            />
                        </div>
                        <div className="grid gap-1.5">
                            <Label htmlFor="warehouse-location">Location</Label>
                            <Input
                                id="warehouse-location"
                                value={form.location}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        location: event.target.value,
                                    })
                                }
                                placeholder="e.g. Chicago, IL"
                                maxLength={255}
                            />
                        </div>
                    </form>

                    <DialogFooter showCloseButton={false}>
                        <Button
                            variant="outline"
                            onClick={() => setDialogOpen(false)}
                            disabled={submitting}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="submit"
                            form="inventory-warehouse-form"
                            disabled={submitting}
                        >
                            {submitting
                                ? editing
                                    ? "Saving…"
                                    : "Creating…"
                                : editing
                                  ? "Save changes"
                                  : "Create warehouse"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog
                open={deleting !== null}
                onOpenChange={(open) => {
                    if (!open && !deletingBusy) setDeleting(null);
                }}
            >
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Archive warehouse?</DialogTitle>
                        <DialogDescription>
                            {deleting
                                ? `${deleting.name} will be archived and hidden from the list. Remaining stock can be written off via Adjust stock, but it cannot be archived while reservations are open — and it stops receiving new stock movements until reactivated.`
                                : ""}
                        </DialogDescription>
                    </DialogHeader>

                    {deleteError ? (
                        <InventoryError message={deleteError} />
                    ) : null}

                    <DialogFooter showCloseButton={false}>
                        <Button
                            variant="outline"
                            onClick={() => setDeleting(null)}
                            disabled={deletingBusy}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => void handleDelete()}
                            disabled={deletingBusy}
                        >
                            {deletingBusy ? "Archiving…" : "Archive"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
