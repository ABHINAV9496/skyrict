"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { CreditCard, FileText, LoaderCircle, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
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
import { registerPaymentIntent, extractVendorRef } from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { onApiError } from "@/lib/api/error-toast";

const PAYMENT_METHODS = [
    { value: "bank_transfer", label: "Bank transfer" },
    { value: "cash", label: "Cash" },
    { value: "card", label: "Card" },
    { value: "check", label: "Check" },
    { value: "wire", label: "Wire" },
] as const;

const paymentSchema = z.object({
    amount: z.string().trim().min(1, "Amount is required"),
    paid_at: z.string().min(1, "Date is required"),
    method: z.string().min(1, "Method is required"),
    reference: z
        .string()
        .trim()
        .max(120, "Reference is at most 120 characters"),
});

type PaymentValues = z.infer<typeof paymentSchema>;

interface RecordPaymentDialogProps {
    onRecorded: () => void;
}

export function RecordPaymentDialog({ onRecorded }: RecordPaymentDialogProps) {
    const [open, setOpen] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [vendorRef, setVendorRef] = useState<string | null>(null);
    const [vendorRefLoading, setVendorRefLoading] = useState(false);
    const vendorRefTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
        null,
    );

    const {
        register,
        handleSubmit,
        watch,
        setValue,
        reset,
        formState: { errors, isSubmitting },
    } = useForm<PaymentValues>({
        resolver: zodResolver(paymentSchema),
        defaultValues: {
            amount: "",
            paid_at: new Date().toISOString().slice(0, 16),
            method: "bank_transfer",
            reference: "",
        },
    });

    const referenceValue = watch("reference");
    const methodValue = watch("method");

    const doExtractVendorRef = useCallback(async (ref: string) => {
        if (!ref.trim()) {
            setVendorRef(null);
            return;
        }
        setVendorRefLoading(true);
        try {
            const result = await extractVendorRef(ref);
            setVendorRef(result);
        } catch {
            setVendorRef(null);
        } finally {
            setVendorRefLoading(false);
        }
    }, []);

    useEffect(() => {
        if (vendorRefTimerRef.current) clearTimeout(vendorRefTimerRef.current);
        vendorRefTimerRef.current = setTimeout(() => {
            void doExtractVendorRef(referenceValue);
        }, 400);
        return () => {
            if (vendorRefTimerRef.current)
                clearTimeout(vendorRefTimerRef.current);
        };
    }, [referenceValue, doExtractVendorRef]);

    function onClose() {
        setOpen(false);
        reset();
        setVendorRef(null);
        setSubmitError(null);
    }

    async function onSubmit(values: PaymentValues) {
        setSubmitError(null);
        try {
            const amountNum = Number(values.amount);
            if (!Number.isFinite(amountNum) || amountNum <= 0) {
                setSubmitError("Enter a positive amount.");
                return;
            }
            await registerPaymentIntent({
                amount: amountNum,
                paid_at: new Date(values.paid_at).toISOString(),
                method: values.method,
                reference: values.reference || undefined,
                source_ref: vendorRef ?? undefined,
                source: "manual",
            });
            onClose();
            onRecorded();
        } catch (err) {
            setSubmitError(
                err instanceof ApiError
                    ? err.message
                    : "Could not register the payment.",
            );
            onApiError(err);
        }
    }

    return (
        <Dialog
            open={open}
            onOpenChange={(v) => (v ? setOpen(true) : onClose())}
        >
            <DialogTrigger asChild>
                <Button type="button" size="sm" variant="outline">
                    <CreditCard aria-hidden="true" className="size-3.5" />
                    Record payment
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <CreditCard aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>Record a payment</DialogTitle>
                        <DialogDescription>
                            Register a receipt so the matching engine can link
                            it to an outstanding invoice.
                        </DialogDescription>
                    </DialogHeader>
                </div>
                <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="pay-amount">Amount</Label>
                            <Input
                                id="pay-amount"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                placeholder="0.00"
                                aria-invalid={errors.amount ? true : undefined}
                                {...register("amount")}
                            />
                            {errors.amount ? (
                                <p
                                    role="alert"
                                    className="text-xs font-medium text-destructive"
                                >
                                    {errors.amount.message}
                                </p>
                            ) : null}
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="pay-date">Paid at</Label>
                            <Input
                                id="pay-date"
                                type="datetime-local"
                                aria-invalid={errors.paid_at ? true : undefined}
                                {...register("paid_at")}
                            />
                            {errors.paid_at ? (
                                <p
                                    role="alert"
                                    className="text-xs font-medium text-destructive"
                                >
                                    {errors.paid_at.message}
                                </p>
                            ) : null}
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <Label htmlFor="pay-method">Method</Label>
                        <Select
                            value={methodValue}
                            onValueChange={(v) => setValue("method", v)}
                        >
                            <SelectTrigger id="pay-method" className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {PAYMENT_METHODS.map((pm) => (
                                    <SelectItem key={pm.value} value={pm.value}>
                                        {pm.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {errors.method ? (
                            <p
                                role="alert"
                                className="text-xs font-medium text-destructive"
                            >
                                {errors.method.message}
                            </p>
                        ) : null}
                    </div>

                    <div className="space-y-1.5">
                        <Label htmlFor="pay-reference">Reference</Label>
                        <Input
                            id="pay-reference"
                            placeholder="e.g. Payment for Invoice INV-2026-0001"
                            aria-invalid={errors.reference ? true : undefined}
                            {...register("reference")}
                        />
                        {errors.reference ? (
                            <p
                                role="alert"
                                className="text-xs font-medium text-destructive"
                            >
                                {errors.reference.message}
                            </p>
                        ) : null}
                    </div>

                    {vendorRef ? (
                        <div className="rounded-lg border border-dashed border-emerald-400/60 bg-emerald-500/5 p-3 text-sm">
                            <div className="flex items-center gap-2">
                                <FileText
                                    aria-hidden="true"
                                    className="size-3.5 text-emerald-600 dark:text-emerald-400"
                                />
                                <span className="text-muted-foreground">
                                    Vendor invoice no.
                                </span>
                                <span className="font-mono font-semibold text-foreground">
                                    {vendorRef}
                                </span>
                            </div>
                            <p className="mt-1 text-xs text-muted-foreground">
                                Auto-extracted from reference and saved as
                                source_ref.
                            </p>
                        </div>
                    ) : vendorRefLoading ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <LoaderCircle
                                aria-hidden="true"
                                className="size-3 animate-spin"
                            />
                            Extracting vendor ref…
                        </div>
                    ) : null}

                    {submitError ? (
                        <p
                            role="alert"
                            className="text-sm font-medium text-destructive"
                        >
                            {submitError}
                        </p>
                    ) : null}

                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={onClose}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={isSubmitting}>
                            {isSubmitting ? (
                                <LoaderCircle
                                    aria-hidden="true"
                                    className="size-4 animate-spin"
                                />
                            ) : (
                                <Plus aria-hidden="true" className="size-4" />
                            )}
                            Record payment
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}
