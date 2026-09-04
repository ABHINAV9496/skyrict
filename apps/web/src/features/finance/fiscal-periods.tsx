"use client";

import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarDays, LoaderCircle, Lock, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
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
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
  closeFiscalPeriod,
  createFiscalPeriod,
  getCloseChecklist,
  listFiscalPeriods,
  type CloseChecklist,
  type FiscalPeriod,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate } from "@/lib/finance/format";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import { TableToolbar } from "@/features/finance/components/table-toolbar";
import {
  PeriodSelector,
  defaultPeriodValue,
  resolvePeriodRange,
  type PeriodValue,
} from "@/features/finance/components/period-selector";
import { StatusBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState, FinanceErrorState } from "@/features/finance/components/state-cards";
import { CloseChecklistWidget } from "@/features/finance/components/automation-widgets";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; periods: FiscalPeriod[]; busy: string | null };

const periodSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(100, "Names are at most 100 characters"),
  start_date: z.string().min(1, "Start date is required"),
  end_date: z.string().min(1, "End date is required"),
});

type PeriodValues = z.infer<typeof periodSchema>;

function CreateFiscalPeriodDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PeriodValues>({
    resolver: zodResolver(periodSchema),
    defaultValues: {
      name: "",
      start_date: new Date().toISOString().slice(0, 10),
      end_date: new Date().toISOString().slice(0, 10),
    },
  });

  async function onSubmit(values: PeriodValues) {
    if (values.end_date < values.start_date) {
      setSubmitError("The end date must be on or after the start date.");
      return;
    }
    setSubmitError(null);
    try {
      await createFiscalPeriod(values);
      setOpen(false);
      reset();
      onCreated();
    } catch (error) {
      setSubmitError(
        error instanceof ApiError ? error.message : "The fiscal period could not be created.",
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden="true" className="size-4" />
          New period
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <CalendarDays aria-hidden="true" className="size-5" />
          </div>
          <DialogHeader>
            <DialogTitle>New fiscal period</DialogTitle>
            <DialogDescription>
              Periods must not overlap. Posting requires an open period that covers the entry date.
            </DialogDescription>
          </DialogHeader>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="period-name">Name</Label>
            <Input id="period-name" placeholder="e.g. FY 2026" aria-invalid={errors.name ? true : undefined} {...register("name")} />
            {errors.name ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.name.message}
              </p>
            ) : null}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="period-start">Start date</Label>
              <Input id="period-start" type="date" aria-invalid={errors.start_date ? true : undefined} {...register("start_date")} />
              {errors.start_date ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.start_date.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="period-end">End date</Label>
              <Input id="period-end" type="date" aria-invalid={errors.end_date ? true : undefined} {...register("end_date")} />
              {errors.end_date ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.end_date.message}
                </p>
              ) : null}
            </div>
          </div>
          {submitError ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {submitError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <Plus aria-hidden="true" className="size-4" />
              )}
              Create period
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const columns: FinanceColumn<FiscalPeriod>[] = [
  { label: "Name", render: (period) => period.name },
  { label: "Start", render: (period) => formatDate(period.start_date) },
  { label: "End", render: (period) => formatDate(period.end_date) },
  {
    label: "Status",
    render: (period) =>
      period.is_closed ? (
        <StatusBadge tone="muted">
          <Lock aria-hidden="true" className="size-3" />
          Closed
        </StatusBadge>
      ) : (
        <StatusBadge tone="success">Open</StatusBadge>
      ),
  },
];

export function FinanceFiscalPeriods() {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const canApprove = hasPermission(permissions, "erp.finance.approve");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());
  const [checklistPeriodId, setChecklistPeriodId] = useState<string>("");
  const [checklist, setChecklist] = useState<CloseChecklist | null>(null);
  const [checklistLoading, setChecklistLoading] = useState(false);
  const [checklistError, setChecklistError] = useState<string | null>(null);

  const loadChecklist = useCallback(async (periodId: string) => {
    if (!periodId) {
      setChecklist(null);
      setChecklistLoading(false);
      setChecklistError(null);
      return;
    }
    setChecklistLoading(true);
    setChecklistError(null);
    try {
      setChecklist(await getCloseChecklist(periodId));
    } catch (error) {
      setChecklistError(
        error instanceof ApiError ? error.message : "Could not load the close checklist.",
      );
      setChecklist(null);
    } finally {
      setChecklistLoading(false);
    }
  }, []);

  // Default the checklist to the first period once loaded.
  useEffect(() => {
    if (status.state === "ready" && status.periods.length > 0 && !checklistPeriodId) {
      setChecklistPeriodId(status.periods[0].id);
      void loadChecklist(status.periods[0].id);
    }
  }, [status, checklistPeriodId, loadChecklist]);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const periods = await listFiscalPeriods();
      setStatus({ state: "ready", periods, busy: null });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load fiscal periods.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onClose(periodId: string) {
    if (status.state !== "ready") return;
    if (!window.confirm("Close this fiscal period? It will be frozen and can no longer receive postings.")) {
      return;
    }
    setStatus({ ...status, busy: periodId });
    try {
      await closeFiscalPeriod(periodId);
      await load();
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not close the fiscal period.",
      });
    }
  }

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Fiscal Periods"
          description="Open and closed accounting periods."
          icon={CalendarDays}
        />
        <TableSkeleton rows={5} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Fiscal Periods"
          description="Open and closed accounting periods."
          icon={CalendarDays}
        />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  const actionColumn: FinanceColumn<FiscalPeriod> = {
    label: "",
    align: "right",
    render: (period) =>
      !period.is_closed && canApprove ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={status.busy !== null}
          onClick={() => void onClose(period.id)}
        >
          {status.busy === period.id ? (
            <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
          ) : null}
          Close
        </Button>
      ) : null,
  };

  const range = resolvePeriodRange(periodValue);
  const visiblePeriods = status.periods.filter((period) => {
    if (range.from && period.end_date < range.from) return false;
    if (range.to && period.start_date > range.to) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <PageHeader
          title="Fiscal Periods"
          description="Open and closed accounting periods."
          icon={CalendarDays}
        />
        <TableToolbar
          period={
            <PeriodSelector
              value={periodValue}
              onChange={setPeriodValue}
              periods={status.periods}
              label="Period"
            />
          }
          actions={canWrite ? <CreateFiscalPeriodDialog onCreated={() => void load()} /> : null}
        />
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="checklist-period">Period checklist</Label>
            <Select value={checklistPeriodId} onValueChange={(value) => void loadChecklist(value)}>
              <SelectTrigger id="checklist-period" className="w-64">
                <SelectValue placeholder="Select a period" />
              </SelectTrigger>
              <SelectContent>
                {status.periods.map((period) => (
                  <SelectItem key={period.id} value={period.id}>
                    {period.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {checklistError ? (
          <FinanceErrorState message={checklistError} />
        ) : (
          <CloseChecklistWidget list={checklist} loading={checklistLoading} />
        )}
      </div>

      {visiblePeriods.length === 0 ? (
        <FinanceEmptyState
          icon={CalendarDays}
          title={status.periods.length === 0 ? "No fiscal periods yet" : "No periods in this year"}
          description={
            status.periods.length === 0
              ? "Create a period covering your entry dates so postings can be made."
              : "Try a different year - no periods fall within the selected range."
          }
        />
      ) : (
        <FinanceTable
          columns={[...columns, actionColumn]}
          rows={visiblePeriods}
          getKey={(period) => period.id}
          footer={
            periodValue.granularity === "all"
              ? `${visiblePeriods.filter((period) => !period.is_closed).length} open · ${visiblePeriods.length} total`
              : `${visiblePeriods.length} periods in the selected range`
          }
        />
      )}
    </div>
  );
}
