"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, SlidersHorizontal } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import {
  SearchableSelect,
  type SearchableSelectOption,
} from "@/components/dashboard/shared/searchable-select";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useModuleAccess } from "@/lib/access/modules";
import {
  getPayrollSettings,
  updatePayrollSettings,
  type PayrollRounding,
} from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready" };

type Notice = { tone: "success" | "error"; text: string };

const ROUNDING_OPTIONS: { value: PayrollRounding; label: string }[] = [
  { value: "nearest", label: "Nearest" },
  { value: "up", label: "Always up" },
  { value: "down", label: "Always down" },
];

export function PayrollSettingsClient() {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.payroll.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [defaultCurrency, setDefaultCurrency] = useState("USD");
  const [pfRate, setPfRate] = useState("0");
  const [taxRate, setTaxRate] = useState("0");
  const [rounding, setRounding] = useState<PayrollRounding>("nearest");
  const [aiAutomationEnabled, setAiAutomationEnabled] = useState(true);
  const [jeBridgeEnabled, setJeBridgeEnabled] = useState(true);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [saving, setSaving] = useState(false);

  const roundingOptions = useMemo<SearchableSelectOption[]>(
    () =>
      ROUNDING_OPTIONS.map((option) => ({
        value: option.value,
        label: option.label,
      })),
    [],
  );

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const settings = await getPayrollSettings();
      if (settings) {
        setDefaultCurrency(settings.defaultCurrency);
        setPfRate(settings.pfRate);
        setTaxRate(settings.taxRate);
        setRounding(settings.rounding);
        setAiAutomationEnabled(settings.aiAutomationEnabled);
        setJeBridgeEnabled(settings.jeBridgeEnabled);
      }
      setStatus({ state: "ready" });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load payroll settings.";
      setStatus({ state: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !canWrite) return;
    if (!/^[A-Za-z]{3}$/.test(defaultCurrency)) {
      setNotice({ tone: "error", text: "Currency must be a 3-letter code." });
      return;
    }
    if (!Number.isFinite(Number(pfRate)) || !Number.isFinite(Number(taxRate))) {
      setNotice({ tone: "error", text: "Rates must be numbers." });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      await updatePayrollSettings({
        defaultCurrency: defaultCurrency.toUpperCase(),
        pfRate: pfRate.trim(),
        taxRate: taxRate.trim(),
        rounding,
        aiAutomationEnabled,
        jeBridgeEnabled,
      });
      setNotice({ tone: "success", text: "Payroll settings saved." });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not save settings.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll settings"
        description="Defaults every payroll run is calculated from."
        icon={SlidersHorizontal}
      />

      {notice ? (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={cn(
            "rounded-lg border px-3 py-2 text-sm font-medium",
            notice.tone === "error"
              ? "border-destructive/40 bg-destructive/5 text-destructive"
              : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
          )}
        >
          {notice.text}
        </div>
      ) : null}

      {status.state === "loading" ? (
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm text-muted-foreground">Loading…</p>
        </div>
      ) : null}

      {status.state === "error" ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
          <p className="text-sm font-medium text-destructive">{status.message}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => void load()}
          >
            Try again
          </Button>
        </div>
      ) : null}

      {status.state === "ready" ? (
        <form
          onSubmit={(event) => void onSubmit(event)}
          className="max-w-lg space-y-6 rounded-xl border border-border bg-card p-5"
        >
          <div className="space-y-1.5">
            <Label htmlFor="default-currency">Default currency</Label>
            <Input
              id="default-currency"
              maxLength={3}
              className="w-32 uppercase"
              value={defaultCurrency}
              onChange={(event) =>
                setDefaultCurrency(event.target.value.toUpperCase())
              }
              required
            />
            <p className="text-xs text-muted-foreground">
              Three-letter ISO code, e.g. USD or INR.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="pf-rate">Provident fund rate</Label>
              <Input
                id="pf-rate"
                inputMode="decimal"
                placeholder="0.07"
                value={pfRate}
                onChange={(event) => setPfRate(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                As a decimal — 0.07 equals 7%.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tax-rate">Tax rate</Label>
              <Input
                id="tax-rate"
                inputMode="decimal"
                placeholder="0.12"
                value={taxRate}
                onChange={(event) => setTaxRate(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                As a decimal — 0.12 equals 12%.
              </p>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rounding">Net pay rounding</Label>
            <SearchableSelect
              id="rounding"
              options={roundingOptions}
              value={rounding}
              onValueChange={(value) => setRounding(value as PayrollRounding)}
              placeholder="Rounding"
            />
            <p className="text-xs text-muted-foreground">
              How computed net pay is rounded before it&apos;s recorded.
            </p>
          </div>
          <div className="space-y-3 rounded-lg border border-border p-4">
            <label className="flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={aiAutomationEnabled}
                onCheckedChange={(value) => setAiAutomationEnabled(value === true)}
              />
              Auto-schedule runs for approval
            </label>
            <p className="text-xs text-muted-foreground">
              Lets the AI orchestration layer pick up approved schedules and
              notify users when their payslips are ready.
            </p>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={jeBridgeEnabled}
                onCheckedChange={(value) => setJeBridgeEnabled(value === true)}
              />
              Post accrual journal entries to Finance
            </label>
            <p className="text-xs text-muted-foreground">
              When a run is marked paid, drafts the salary accrual journal
              entry in Finance (accounts 5010 / 2010 / 2020).
            </p>
          </div>
          {canWrite ? (
            <div className="flex justify-end">
              <Button type="submit" disabled={saving}>
                {saving ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : null}
                Save settings
              </Button>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Your role can view these settings. Ask for{" "}
              <span className="font-medium text-foreground">erp.payroll.write</span>{" "}
              to change them.
            </p>
          )}
        </form>
      ) : null}
    </div>
  );
}
