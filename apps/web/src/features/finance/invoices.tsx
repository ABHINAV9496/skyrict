"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
    useController,
    useFieldArray,
    useForm,
    type Control,
} from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
    ArrowRight,
    Check,
    ChevronsUpDown,
    LoaderCircle,
    Mail,
    Plus,
    ReceiptText,
    Trash2,
} from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { useDialogDropdown } from "@/components/ui/dialog-dropdown";
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
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
    batchReminders,
    createInvoice,
    getFxContext,
    getFxRate,
    listAccounts,
    listCustomers,
    listFiscalPeriods,
    listInvoices,
    suggestInvoiceLines,
    upsertFxRate,
    type Account,
    type Customer,
    type FiscalPeriod,
    type FxContext,
    type Invoice,
    type InvoiceLineSuggestion,
    type ReminderDraft,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import { PaymentMatchInbox } from "@/features/finance/components/payment-match-inbox";
import { CustomerPaymentAnalytics } from "@/features/finance/components/customer-payment-analytics";
import {
    PeriodSelector,
    defaultPeriodValue,
    resolvePeriodRange,
    today,
    type PeriodValue,
} from "@/features/finance/components/period-selector";
import { InvoiceStatusBadge } from "@/features/finance/components/status-badge";
import {
    FinanceEmptyState,
    FinanceErrorState,
} from "@/features/finance/components/state-cards";
import { AccountCombobox } from "@/features/finance/components/account-combobox";
import {
    LineItemsTable,
    type LineItemColumn,
} from "@/features/finance/components/line-items-table";
import { TableToolbar } from "@/features/finance/components/table-toolbar";
import { cn } from "@/lib/utils";

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; invoices: Invoice[] };

// ---------------------------------------------------------------------------
// Customer combobox (searchable dropdown)
// ---------------------------------------------------------------------------

function CustomerCombobox({
    customers,
    value,
    onChange,
    invalid,
}: {
    customers: Customer[];
    value: string;
    onChange: (id: string) => void;
    invalid?: boolean;
}) {
    const triggerRef = useRef<HTMLDivElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const justSelectedRef = useRef(false);
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const [highlighted, setHighlighted] = useState(0);
    const { anchorRef, popoverRef, render } = useDialogDropdown(open);

    const setTrigger = useCallback(
        (el: HTMLDivElement | null) => {
            triggerRef.current = el;
            anchorRef.current = el;
        },
        [anchorRef],
    );

    const selected = useMemo(
        () => customers.find((c) => c.id === value) ?? null,
        [customers, value],
    );

    const filtered = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) return customers;
        return customers.filter(
            (c) =>
                c.name.toLowerCase().includes(needle) ||
                c.customer_code.toLowerCase().includes(needle) ||
                (c.email ?? "").toLowerCase().includes(needle),
        );
    }, [customers, query]);

    useEffect(() => {
        setHighlighted(0);
    }, [filtered.length, query]);

    useEffect(() => {
        if (!open) return;
        const list = listRef.current;
        if (!list) return;
        const item = list.children[highlighted] as HTMLElement | undefined;
        item?.scrollIntoView({ block: "nearest" });
    }, [highlighted, open]);

    const select = useCallback(
        (customer: Customer) => {
            justSelectedRef.current = true;
            onChange(customer.id);
            setQuery(`${customer.name} (${customer.customer_code})`);
            setOpen(false);
        },
        [onChange],
    );

    useEffect(() => {
        if (!open) return;
        function handleClickOutside(event: MouseEvent) {
            const target = event.target as Node;
            if (
                triggerRef.current &&
                !triggerRef.current.contains(target) &&
                !popoverRef.current?.contains(target)
            ) {
                setOpen(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, [open, popoverRef]);

    function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setHighlighted((index) =>
                Math.min(index + 1, Math.max(filtered.length - 1, 0)),
            );
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setHighlighted((index) => Math.max(index - 1, 0));
        } else if (event.key === "Enter") {
            event.preventDefault();
            const match =
                filtered[highlighted] ??
                filtered.find(
                    (c) => c.name.toLowerCase() === query.trim().toLowerCase(),
                );
            if (match) select(match);
            else setOpen(false);
        } else if (event.key === "Escape") {
            setOpen(false);
        }
    }

    function handleBlur() {
        setTimeout(() => {
            if (justSelectedRef.current) {
                justSelectedRef.current = false;
                return;
            }
            setQuery(
                selected ? `${selected.name} (${selected.customer_code})` : "",
            );
        }, 150);
    }

    return (
        <>
            <div ref={setTrigger} className="relative">
                <Input
                    value={query}
                    aria-invalid={invalid || undefined}
                    aria-haspopup="listbox"
                    aria-expanded={open}
                    placeholder="Search customer by name or code…"
                    onChange={(event) => {
                        setQuery(event.target.value);
                        setHighlighted(0);
                        setOpen(true);
                    }}
                    onMouseDown={() => {
                        setOpen(true);
                    }}
                    onKeyDown={handleKeyDown}
                    onBlur={handleBlur}
                    className="pr-7"
                />
                <ChevronsUpDown
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
                />
            </div>
            {render(
                <div
                    ref={listRef}
                    role="listbox"
                    className="max-h-56 min-w-64 w-full overflow-y-auto rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md outline-none"
                >
                    {filtered.length === 0 ? (
                        <p className="px-2 py-3 text-center text-sm text-muted-foreground">
                            No matching customers
                        </p>
                    ) : (
                        filtered.map((customer, index) => (
                            <button
                                key={customer.id}
                                type="button"
                                role="option"
                                aria-selected={customer.id === value}
                                onMouseEnter={() => setHighlighted(index)}
                                onMouseDown={(event) => {
                                    event.preventDefault();
                                    select(customer);
                                }}
                                className={cn(
                                    "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                                    index === highlighted
                                        ? "bg-muted"
                                        : "hover:bg-muted",
                                )}
                            >
                                <span className="min-w-0 truncate">
                                    <span className="font-medium">
                                        {customer.name}
                                    </span>
                                    <span className="ml-1 text-muted-foreground">
                                        ({customer.customer_code})
                                    </span>
                                    {customer.email ? (
                                        <span className="ml-1 text-xs text-muted-foreground">
                                            · {customer.email}
                                        </span>
                                    ) : null}
                                </span>
                                {customer.id === value ? (
                                    <Check
                                        aria-hidden="true"
                                        className="size-3.5 shrink-0 text-primary"
                                    />
                                ) : null}
                            </button>
                        ))
                    )}
                </div>,
            )}
        </>
    );
}

const invoiceLineSchema = z.object({
    description: z
        .string()
        .trim()
        .min(1, "Description is required")
        .max(500, "Max 500 characters"),
    account_code: z.string().trim().min(1, "Account code is required"),
    quantity: z.string().trim().min(1, "Quantity is required"),
    unit_price: z.string().trim().min(1, "Unit price is required"),
});

const invoiceSchema = z.object({
    customer_id: z.string().trim().min(1, "Customer is required"),
    invoice_date: z.string().min(1, "Invoice date is required"),
    due_date: z.string().min(1, "Due date is required"),
    lines: z.array(invoiceLineSchema).min(1, "Add at least one line"),
});

type InvoiceValues = z.infer<typeof invoiceSchema>;

function InvoiceAccountRow({
    control,
    accounts,
    index,
    errorMessage,
    inputRef,
}: {
    control: Control<InvoiceValues>;
    accounts: Account[];
    index: number;
    errorMessage?: string;
    inputRef?: (el: HTMLInputElement | null) => void;
}) {
    const { field } = useController({
        control,
        name: `lines.${index}.account_code`,
    });
    return (
        <>
            <AccountCombobox
                accounts={accounts}
                value={field.value}
                onChange={field.onChange}
                invalid={Boolean(errorMessage)}
                inputRef={inputRef}
            />
            {errorMessage ? (
                <p
                    role="alert"
                    className="text-xs font-medium text-destructive"
                >
                    {errorMessage}
                </p>
            ) : null}
        </>
    );
}

function LineDescriptionField({
    value,
    onChange,
    invalid,
}: {
    value: string;
    onChange: (suggestion: InvoiceLineSuggestion | null, value: string) => void;
    invalid?: boolean;
}) {
    // SKY-67 C1: debounced line-item suggestion dropdown (read-only, never
    // auto-inserts or auto-approves - selecting just fills description + account).
    const [suggestions, setSuggestions] = useState<InvoiceLineSuggestion[]>([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const controllerRef = useRef<AbortController | null>(null);
    const justPickedRef = useRef(false);
    const wrapperRef = useRef<HTMLDivElement | null>(null);
    const { anchorRef, render } = useDialogDropdown(open);

    const setWrapper = useCallback(
        (el: HTMLDivElement | null) => {
            wrapperRef.current = el;
            anchorRef.current = el;
        },
        [anchorRef],
    );

    useEffect(() => {
        const text = value.trim();
        if (justPickedRef.current || text.length < 2) {
            justPickedRef.current = false;
            setSuggestions([]);
            setOpen(false);
            return;
        }
        const controller = new AbortController();
        controllerRef.current?.abort();
        controllerRef.current = controller;
        setLoading(true);
        setOpen(true);
        const timer = setTimeout(() => {
            void suggestInvoiceLines(text)
                .then((hits) => {
                    if (!controller.signal.aborted) {
                        setSuggestions(hits.slice(0, 5));
                        setOpen(hits.length > 0);
                    }
                })
                .catch(() => {
                    if (!controller.signal.aborted) {
                        setSuggestions([]);
                        setOpen(false);
                    }
                })
                .finally(() => {
                    if (!controller.signal.aborted) setLoading(false);
                });
        }, 250);
        return () => {
            controller.abort();
            clearTimeout(timer);
        };
    }, [value]);

    function pick(suggestion: InvoiceLineSuggestion) {
        justPickedRef.current = true;
        onChange(suggestion, suggestion.description);
        setSuggestions([]);
        setOpen(false);
    }

    return (
        <div ref={setWrapper} className="relative">
            <Input
                placeholder="Description"
                aria-invalid={invalid}
                aria-expanded={open}
                value={value}
                onChange={(event) => onChange(null, event.target.value)}
            />
            {render(
                open ? (
                    <ul
                        className="w-full overflow-hidden rounded-md border border-border bg-popover text-sm shadow-lg"
                        onMouseDown={(event) => event.preventDefault()}
                    >
                        {loading && suggestions.length === 0 ? (
                            <li>
                                <span className="block px-3 py-2 text-sm text-muted-foreground">
                                    Searching…
                                </span>
                            </li>
                        ) : (
                            suggestions.map((suggestion) => (
                                <li
                                    key={`${suggestion.description}-${suggestion.account_code}`}
                                >
                                    <button
                                        type="button"
                                        className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-accent"
                                        onClick={() => pick(suggestion)}
                                    >
                                        <span className="w-full truncate font-medium text-foreground">
                                            {suggestion.description}
                                        </span>
                                        <span className="w-full truncate text-xs text-muted-foreground">
                                            {suggestion.account_code} ·{" "}
                                            {suggestion.account_name}
                                        </span>
                                    </button>
                                </li>
                            ))
                        )}
                    </ul>
                ) : null,
            )}
        </div>
    );
}

function CreateInvoiceDialog() {
    const router = useRouter();
    const [open, setOpen] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [customers, setCustomers] = useState<Customer[]>([]);
    const accountInputRefs = useRef<(HTMLInputElement | null)[]>([]);
    // SKY-67 C2: invoice currency selector + FX guardrail (never silent conversion).
    const [fxContext, setFxContext] = useState<FxContext | null>(null);
    const [currency, setCurrency] = useState("USD");
    const [fxRate, setFxRate] = useState<number | null>(null);
    const [fxStatus, setFxStatus] = useState<
        "idle" | "loading" | "ready" | "missing"
    >("idle");
    const [rateInput, setRateInput] = useState("");
    const [settingRate, setSettingRate] = useState(false);
    const currencyTouchedRef = useRef(false);

    const {
        register,
        handleSubmit,
        control,
        watch,
        reset,
        setValue,
        formState: { errors, isSubmitting },
    } = useForm<InvoiceValues>({
        resolver: zodResolver(invoiceSchema),
        defaultValues: {
            customer_id: "",
            invoice_date: new Date().toISOString().slice(0, 10),
            due_date: new Date().toISOString().slice(0, 10),
            lines: [
                {
                    description: "",
                    account_code: "",
                    quantity: "1",
                    unit_price: "",
                },
            ],
        },
    });

    const { fields, append, remove } = useFieldArray({
        control,
        name: "lines",
    });
    const lines = watch("lines");
    const subtotal = useMemo(
        () =>
            lines.reduce((sum, line) => {
                const quantity = Number(line.quantity);
                const price = Number(line.unit_price);
                return (
                    sum +
                    (Number.isFinite(quantity) && Number.isFinite(price)
                        ? quantity * price
                        : 0)
                );
            }, 0),
        [lines],
    );

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        currencyTouchedRef.current = false;
        void Promise.all([listAccounts(true), listCustomers(), getFxContext()])
            .then(([fetchedAccounts, fetchedCustomers, context]) => {
                if (!cancelled) {
                    setAccounts(fetchedAccounts);
                    setCustomers(fetchedCustomers.filter((c) => c.is_active));
                    setFxContext(context);
                    setCurrency(context.default_currency);
                    setFxRate(null);
                    setFxStatus("idle");
                    setRateInput("");
                }
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [open]);

    const invoiceDate = watch("invoice_date");

    useEffect(() => {
        if (!open || !fxContext) return;
        const base = fxContext.default_currency;
        const selected = currency || base;
        if (selected === base) {
            setFxRate(null);
            setFxStatus("idle");
            return;
        }
        if (!invoiceDate) return;
        let cancelled = false;
        setFxStatus("loading");
        getFxRate(selected, invoiceDate)
            .then((entry) => {
                if (!cancelled) {
                    setFxRate(entry.rate);
                    setFxStatus("ready");
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setFxRate(null);
                    setFxStatus("missing");
                }
            });
        return () => {
            cancelled = true;
        };
    }, [open, fxContext, currency, invoiceDate]);

    const defaultCurrency = fxContext?.default_currency ?? "USD";
    const needsRate = currency !== "" && currency !== defaultCurrency;
    const fmt = (value: number) =>
        currency && currency !== "USD"
            ? `${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`
            : formatMoney(value);

    async function saveRate() {
        const value = Number(rateInput);
        if (!Number.isFinite(value) || value <= 0) return;
        setSettingRate(true);
        try {
            const stored = await upsertFxRate({
                base_currency: defaultCurrency,
                quote_currency: currency,
                effective_date:
                    invoiceDate || new Date().toISOString().slice(0, 10),
                rate: value,
            });
            setFxRate(stored.rate);
            setFxStatus("ready");
            setRateInput("");
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The FX rate could not be saved.",
            );
        } finally {
            setSettingRate(false);
        }
    }

    async function onSubmit(values: InvoiceValues) {
        if (values.due_date < values.invoice_date) {
            setSubmitError(
                "The due date must be on or after the invoice date.",
            );
            return;
        }
        setSubmitError(null);
        try {
            const invoice = await createInvoice({
                customer_id: values.customer_id.trim(),
                invoice_date: values.invoice_date,
                due_date: values.due_date,
                currency: currency || undefined,
                lines: values.lines.map((line) => ({
                    description: line.description.trim(),
                    account_code: line.account_code.trim(),
                    quantity: Number(line.quantity),
                    unit_price: Number(line.unit_price),
                })),
            });
            setOpen(false);
            reset();
            router.push(`/dashboard/erp/finance/invoices/${invoice.id}`);
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The invoice could not be created.",
            );
        }
    }

    const lineColumns: LineItemColumn[] = [
        { label: "Description" },
        { label: "Account" },
        { label: "Qty", align: "right", className: "w-20" },
        { label: "Unit price", align: "right", className: "w-28" },
        { label: "Amount", align: "right", className: "w-28" },
        { label: "", className: "w-10" },
    ];

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button>
                    <Plus aria-hidden="true" className="size-4" />
                    New invoice
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-3xl">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <ReceiptText aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>New invoice</DialogTitle>
                        <DialogDescription>
                            A draft manual invoice. Lines post to the revenue
                            account codes you choose.
                        </DialogDescription>
                    </DialogHeader>
                </div>
                <form
                    onSubmit={handleSubmit(onSubmit)}
                    className="max-h-[min(85vh,42rem)] space-y-4 overflow-y-auto pr-1"
                >
                    <div className="grid gap-4 sm:grid-cols-3">
                        <div className="space-y-1.5 sm:col-span-3">
                            <Label htmlFor="invoice-customer">Customer</Label>
                            <CustomerCombobox
                                customers={customers}
                                value={watch("customer_id")}
                                onChange={(id) => {
                                    // react-hook-form's register-based approach needs manual setValue
                                    // But we're using register, so we set via the hidden pattern
                                    const event = {
                                        target: {
                                            value: id,
                                            name: "customer_id",
                                        },
                                    };
                                    register("customer_id").onChange(event);
                                    if (!currencyTouchedRef.current) {
                                        const customer = customers.find(
                                            (c) => c.id === id,
                                        );
                                        if (customer?.currency)
                                            setCurrency(customer.currency);
                                    }
                                }}
                                invalid={Boolean(errors.customer_id)}
                            />
                            {errors.customer_id ? (
                                <p
                                    role="alert"
                                    className="text-xs font-medium text-destructive"
                                >
                                    {errors.customer_id.message}
                                </p>
                            ) : null}
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="invoice-date">Invoice date</Label>
                            <Input
                                id="invoice-date"
                                type="date"
                                aria-invalid={
                                    errors.invoice_date ? true : undefined
                                }
                                {...register("invoice_date")}
                            />
                            {errors.invoice_date ? (
                                <p
                                    role="alert"
                                    className="text-xs font-medium text-destructive"
                                >
                                    {errors.invoice_date.message}
                                </p>
                            ) : null}
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="invoice-due">Due date</Label>
                            <Input
                                id="invoice-due"
                                type="date"
                                aria-invalid={
                                    errors.due_date ? true : undefined
                                }
                                {...register("due_date")}
                            />
                            {errors.due_date ? (
                                <p
                                    role="alert"
                                    className="text-xs font-medium text-destructive"
                                >
                                    {errors.due_date.message}
                                </p>
                            ) : null}
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="invoice-currency">Currency</Label>
                            <select
                                id="invoice-currency"
                                className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-sm shadow-xs outline-none transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50"
                                value={currency}
                                onChange={(event) => {
                                    currencyTouchedRef.current = true;
                                    setCurrency(event.target.value);
                                }}
                            >
                                {(
                                    fxContext?.currencies ?? [defaultCurrency]
                                ).map((code) => (
                                    <option key={code} value={code}>
                                        {code}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>

                    {needsRate ? (
                        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
                            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
                                Invoice currency {currency} is not{" "}
                                {defaultCurrency}.
                            </p>
                            {fxStatus === "ready" && fxRate !== null ? (
                                <p className="mt-1 text-sm text-muted-foreground">
                                    FX rate on file: 1 {currency} = {fxRate}{" "}
                                    {defaultCurrency}. No silent conversion
                                    happens elsewhere; total amount stays in{" "}
                                    {currency}.
                                </p>
                            ) : fxStatus === "missing" ? (
                                <div className="flex flex-wrap items-end gap-2 pt-2">
                                    <div className="space-y-1.5">
                                        <Label htmlFor="fx-rate-input">
                                            Rate per invoice date ({invoiceDate}
                                            )
                                        </Label>
                                        <Input
                                            id="fx-rate-input"
                                            type="number"
                                            inputMode="decimal"
                                            min="0"
                                            step="0.000001"
                                            placeholder={`1 ${currency} = ? ${defaultCurrency}`}
                                            value={rateInput}
                                            onChange={(event) =>
                                                setRateInput(event.target.value)
                                            }
                                            className="w-64"
                                        />
                                    </div>
                                    <Button
                                        type="button"
                                        variant="secondary"
                                        onClick={saveRate}
                                        disabled={settingRate}
                                    >
                                        {settingRate ? (
                                            <LoaderCircle
                                                aria-hidden="true"
                                                className="size-4 animate-spin"
                                            />
                                        ) : null}
                                        Set rate
                                    </Button>
                                </div>
                            ) : (
                                <p className="mt-1 text-sm text-muted-foreground">
                                    Checking for an FX rate…
                                </p>
                            )}
                            <p className="mt-2 text-xs text-muted-foreground">
                                The invoice can only be saved once a rate is on
                                file for this date &amp; currency. Nothing is
                                converted or journaled silently in another
                                currency.
                            </p>
                        </div>
                    ) : null}

                    <div className="space-y-2">
                        <Label>Lines</Label>
                        <LineItemsTable
                            columns={lineColumns}
                            footer={
                                <span className="flex items-center justify-between gap-4">
                                    <span className="text-xs font-medium text-muted-foreground">
                                        Subtotal
                                    </span>
                                    <span className="tabular-nums text-foreground">
                                        {fmt(subtotal)}
                                    </span>
                                </span>
                            }
                            onAddRow={() => {
                                const nextIndex = fields.length;
                                append({
                                    description: "",
                                    account_code: "",
                                    quantity: "1",
                                    unit_price: "",
                                });
                                requestAnimationFrame(() =>
                                    accountInputRefs.current[
                                        nextIndex
                                    ]?.focus(),
                                );
                            }}
                        >
                            {fields.map((field, index) => {
                                const quantity = Number(
                                    watch(`lines.${index}.quantity`) ?? "",
                                );
                                const price = Number(
                                    watch(`lines.${index}.unit_price`) ?? "",
                                );
                                const amount =
                                    Number.isFinite(quantity) &&
                                    Number.isFinite(price)
                                        ? quantity * price
                                        : 0;
                                return (
                                    <tr
                                        key={field.id}
                                        className="border-b border-border/60 last:border-0"
                                    >
                                        <td className="px-3 py-1">
                                            <LineDescriptionField
                                                value={
                                                    (watch(
                                                        `lines.${index}.description`,
                                                    ) as string) ?? ""
                                                }
                                                onChange={(
                                                    suggestion,
                                                    value,
                                                ) => {
                                                    setValue(
                                                        `lines.${index}.description`,
                                                        value,
                                                        {
                                                            shouldValidate: true,
                                                            shouldDirty: true,
                                                            shouldTouch: true,
                                                        },
                                                    );
                                                    // Filling a known line also
                                                    // fills its account code.
                                                    if (
                                                        suggestion &&
                                                        !(watch(
                                                            `lines.${index}.account_code`,
                                                        ) as string)
                                                    ) {
                                                        setValue(
                                                            `lines.${index}.account_code`,
                                                            suggestion.account_code,
                                                            {
                                                                shouldValidate: true,
                                                                shouldDirty: true,
                                                                shouldTouch: true,
                                                            },
                                                        );
                                                    }
                                                }}
                                                invalid={
                                                    errors.lines?.[index]
                                                        ?.description
                                                        ? true
                                                        : undefined
                                                }
                                            />
                                            {errors.lines?.[index]
                                                ?.description ? (
                                                <p
                                                    role="alert"
                                                    className="text-xs font-medium text-destructive"
                                                >
                                                    {
                                                        errors.lines[index]
                                                            ?.description
                                                            ?.message
                                                    }
                                                </p>
                                            ) : null}
                                        </td>
                                        <td className="px-3 py-1">
                                            <InvoiceAccountRow
                                                control={control}
                                                accounts={accounts}
                                                index={index}
                                                errorMessage={
                                                    errors.lines?.[index]
                                                        ?.account_code?.message
                                                }
                                                inputRef={(el) => {
                                                    accountInputRefs.current[
                                                        index
                                                    ] = el;
                                                }}
                                            />
                                        </td>
                                        <td className="px-3 py-1 text-right">
                                            <Input
                                                type="number"
                                                inputMode="decimal"
                                                min="0"
                                                step="1"
                                                placeholder="1"
                                                className="ml-auto text-right"
                                                aria-invalid={
                                                    errors.lines?.[index]
                                                        ?.quantity
                                                        ? true
                                                        : undefined
                                                }
                                                {...register(
                                                    `lines.${index}.quantity`,
                                                )}
                                            />
                                            {errors.lines?.[index]?.quantity ? (
                                                <p
                                                    role="alert"
                                                    className="text-xs font-medium text-destructive"
                                                >
                                                    {
                                                        errors.lines[index]
                                                            ?.quantity?.message
                                                    }
                                                </p>
                                            ) : null}
                                        </td>
                                        <td className="px-3 py-1 text-right">
                                            <Input
                                                type="number"
                                                inputMode="decimal"
                                                min="0"
                                                step="0.01"
                                                placeholder="0.00"
                                                className="ml-auto text-right"
                                                aria-invalid={
                                                    errors.lines?.[index]
                                                        ?.unit_price
                                                        ? true
                                                        : undefined
                                                }
                                                {...register(
                                                    `lines.${index}.unit_price`,
                                                )}
                                            />
                                            {errors.lines?.[index]
                                                ?.unit_price ? (
                                                <p
                                                    role="alert"
                                                    className="text-xs font-medium text-destructive"
                                                >
                                                    {
                                                        errors.lines[index]
                                                            ?.unit_price
                                                            ?.message
                                                    }
                                                </p>
                                            ) : null}
                                        </td>
                                        <td className="px-3 py-1 text-right tabular-nums text-muted-foreground">
                                            {fmt(amount)}
                                        </td>
                                        <td className="px-3 py-1 text-right">
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="icon-sm"
                                                aria-label="Remove line"
                                                disabled={fields.length === 1}
                                                onClick={() => remove(index)}
                                            >
                                                <Trash2
                                                    aria-hidden="true"
                                                    className="size-3.5"
                                                />
                                            </Button>
                                        </td>
                                    </tr>
                                );
                            })}
                        </LineItemsTable>
                        {errors.lines?.message ? (
                            <p
                                role="alert"
                                className="text-xs font-medium text-destructive"
                            >
                                {errors.lines.message}
                            </p>
                        ) : null}
                    </div>

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
                            onClick={() => setOpen(false)}
                        >
                            Cancel
                        </Button>
                        <Button
                            type="submit"
                            disabled={
                                isSubmitting ||
                                (needsRate && fxStatus !== "ready")
                            }
                        >
                            {isSubmitting ? (
                                <LoaderCircle
                                    aria-hidden="true"
                                    className="size-4 animate-spin"
                                />
                            ) : null}
                            Save draft
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

const columns: FinanceColumn<Invoice>[] = [
    { label: "Number", render: (invoice) => invoice.invoice_number },
    { label: "Customer", render: (invoice) => invoice.customer_name ?? "-" },
    { label: "Date", render: (invoice) => formatDate(invoice.invoice_date) },
    { label: "Due", render: (invoice) => formatDate(invoice.due_date) },
    {
        label: "Status",
        render: (invoice) => <InvoiceStatusBadge status={invoice.status} />,
    },
    {
        label: "Total",
        align: "right",
        render: (invoice) => formatMoney(invoice.total),
    },
    {
        label: "Balance",
        align: "right",
        render: (invoice) => {
            if (invoice.status === "voided") return "-";
            if (invoice.status === "paid")
                return <span className="tabular-nums">{formatMoney(0)}</span>;
            return (
                <span className="tabular-nums">
                    {formatMoney(invoice.total)}
                </span>
            );
        },
    },
    {
        label: "",
        align: "right",
        render: (invoice) => (
            <Link
                href={`/dashboard/erp/finance/invoices/${invoice.id}`}
                className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
                View <ArrowRight aria-hidden="true" className="size-3.5" />
            </Link>
        ),
    },
];

function FinanceInvoices() {
    const { permissions } = useModuleAccess();
    const canWrite = hasPermission(permissions, "erp.finance.write");
    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
    const [periodValue, setPeriodValue] =
        useState<PeriodValue>(defaultPeriodValue());
    const [query, setQuery] = useState("");
    const [statusTab, setStatusTab] = useState<string>("all");
    const [batchRemindersState, setBatchRemindersState] = useState<{
        reminders: ReminderDraft[];
        open: boolean;
        loading: boolean;
        error: string | null;
    }>({ reminders: [], open: false, loading: false, error: null });

    async function loadBatchReminders() {
        setBatchRemindersState((prev) => ({
            ...prev,
            loading: true,
            error: null,
            open: true,
        }));
        try {
            const result = await batchReminders();
            setBatchRemindersState((prev) => ({
                ...prev,
                reminders: result.reminders,
                loading: false,
            }));
        } catch (error) {
            setBatchRemindersState((prev) => ({
                ...prev,
                loading: false,
                error:
                    error instanceof ApiError
                        ? error.message
                        : "Could not generate reminders.",
            }));
        }
    }

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const [invoices, fetchedPeriods] = await Promise.all([
                listInvoices({ limit: 200 }),
                listFiscalPeriods(),
            ]);
            setPeriods(fetchedPeriods);
            setStatus({ state: "ready", invoices: invoices.data });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load invoices.",
            });
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    if (status.state === "loading") {
        return (
            <div className="space-y-6">
                <PageHeader
                    title="Invoices"
                    description="Bill customers and track each invoice through issue, approval, and payment."
                    icon={ReceiptText}
                />
                <TableSkeleton rows={6} />
            </div>
        );
    }

    if (status.state === "error") {
        return (
            <div className="space-y-6">
                <PageHeader
                    title="Invoices"
                    description="Bill customers and track each invoice through issue, approval, and payment."
                    icon={ReceiptText}
                />
                <FinanceErrorState
                    message={status.message}
                    onRetry={() => void load()}
                />
            </div>
        );
    }

    const range = resolvePeriodRange(periodValue);
    const analyticsFrom =
        range.from ??
        (periods.length > 0
            ? [...periods].map((period) => period.start_date).sort()[0]
            : today());
    const analyticsTo = range.to ?? today();
    const visibleInvoices = status.invoices.filter((invoice) => {
        if (range.from && invoice.invoice_date < range.from) return false;
        if (range.to && invoice.invoice_date > range.to) return false;
        return true;
    });
    const isOpen = (invoice: Invoice) =>
        invoice.status !== "paid" && invoice.status !== "voided";
    const openInvoices = visibleInvoices.filter(isOpen);
    const overdueInvoices = openInvoices.filter(
        (invoice) => invoice.due_date < today(),
    );

    return (
        <div className="space-y-6">
            <PaymentMatchInbox />
            <div className="space-y-4">
                <PageHeader
                    title="Invoices"
                    description="Bill customers and track each invoice through issue, approval, and payment."
                    icon={ReceiptText}
                />
                <TableToolbar
                    searchPlaceholder="Search invoice number…"
                    searchValue={query}
                    onSearchChange={setQuery}
                    tabs={[
                        {
                            key: "all",
                            label: "All",
                            count: visibleInvoices.length,
                        },
                        {
                            key: "open",
                            label: "Open",
                            count: openInvoices.length,
                        },
                        {
                            key: "paid",
                            label: "Paid",
                            count: visibleInvoices.filter(
                                (i) => i.status === "paid",
                            ).length,
                        },
                        {
                            key: "overdue",
                            label: "Overdue",
                            count: overdueInvoices.length,
                        },
                        { key: "analytics", label: "Analytics" },
                    ]}
                    activeTab={statusTab}
                    onTabChange={setStatusTab}
                    period={
                        <PeriodSelector
                            value={periodValue}
                            onChange={setPeriodValue}
                            periods={periods}
                            label="Invoice period"
                        />
                    }
                    actions={
                        canWrite ? (
                            <div className="flex items-center gap-2">
                                {statusTab === "overdue" &&
                                overdueInvoices.length > 0 ? (
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        disabled={batchRemindersState.loading}
                                        onClick={() =>
                                            void loadBatchReminders()
                                        }
                                    >
                                        {batchRemindersState.loading ? (
                                            <LoaderCircle
                                                aria-hidden="true"
                                                className="size-3.5 animate-spin"
                                            />
                                        ) : (
                                            <Mail
                                                aria-hidden="true"
                                                className="size-3.5"
                                            />
                                        )}
                                        Generate Reminders
                                    </Button>
                                ) : null}
                                <CreateInvoiceDialog />
                            </div>
                        ) : null
                    }
                />
            </div>

            {statusTab === "analytics" ? (
                <CustomerPaymentAnalytics
                    fromDate={analyticsFrom}
                    toDate={analyticsTo}
                />
            ) : status.invoices.length === 0 ? (
                <FinanceEmptyState
                    icon={ReceiptText}
                    title="No invoices yet"
                    description="Create a draft invoice to start billing customers."
                />
            ) : (
                <FinanceTable
                    columns={columns}
                    rows={visibleInvoices.filter((invoice) => {
                        if (statusTab === "open" && !isOpen(invoice))
                            return false;
                        if (statusTab === "paid" && invoice.status !== "paid")
                            return false;
                        if (
                            statusTab === "overdue" &&
                            !overdueInvoices.includes(invoice)
                        )
                            return false;
                        if (query.trim()) {
                            const needle = query.trim().toLowerCase();
                            if (
                                !invoice.invoice_number
                                    .toLowerCase()
                                    .includes(needle)
                            )
                                return false;
                        }
                        return true;
                    })}
                    getKey={(invoice) => invoice.id}
                    footer={`${visibleInvoices.length} invoices in the selected period`}
                />
            )}

            <Dialog
                open={batchRemindersState.open}
                onOpenChange={(v) =>
                    setBatchRemindersState((prev) => ({ ...prev, open: v }))
                }
            >
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>Payment reminders</DialogTitle>
                        <DialogDescription>
                            Drafted for {batchRemindersState.reminders.length}{" "}
                            overdue invoice
                            {batchRemindersState.reminders.length === 1
                                ? ""
                                : "s"}
                            .
                        </DialogDescription>
                    </DialogHeader>
                    {batchRemindersState.error ? (
                        <p
                            role="alert"
                            className="text-xs font-medium text-destructive"
                        >
                            {batchRemindersState.error}
                        </p>
                    ) : null}
                    {batchRemindersState.loading ? (
                        <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                            <LoaderCircle
                                aria-hidden="true"
                                className="size-4 animate-spin"
                            />
                            Generating reminders…
                        </div>
                    ) : (
                        <div className="max-h-72 space-y-2 overflow-auto pr-1">
                            {batchRemindersState.reminders.map((reminder) => (
                                <div
                                    key={reminder.invoice_number}
                                    className="rounded-lg border border-border p-3"
                                >
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-medium text-foreground">
                                            {reminder.invoice_number}
                                        </span>
                                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                                            {reminder.days_overdue} days overdue
                                            · {reminder.tone}
                                        </span>
                                    </div>
                                    <p className="mt-1 text-sm font-medium">
                                        {reminder.subject}
                                    </p>
                                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                        {reminder.body}
                                    </p>
                                </div>
                            ))}
                        </div>
                    )}
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() =>
                                setBatchRemindersState((prev) => ({
                                    ...prev,
                                    open: false,
                                }))
                            }
                        >
                            Close
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

export { CreateInvoiceDialog, FinanceInvoices };
