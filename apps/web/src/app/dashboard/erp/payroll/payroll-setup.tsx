"use client";

import { useCallback, useEffect, useState } from "react";

import { CompensationDialog } from "@/components/dashboard/erp/payroll/compensation-dialog";
import { NewRunDialog } from "@/components/dashboard/erp/payroll/run-dialog";
import {
  SetupChecklist,
  type SetupStep,
} from "@/components/dashboard/shared/setup-checklist";
import { useModuleAccess } from "@/lib/access/modules";
import { listEmployees, type Employee } from "@/lib/api/hr-api";
import { listPayrollRuns } from "@/lib/api/payroll-api";

type LoadState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready" };

export function PayrollSetup() {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.payroll.write");

  const [status, setStatus] = useState<LoadState>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [hasRuns, setHasRuns] = useState(false);

  const [compensationOpen, setCompensationOpen] = useState(false);
  const [runOpen, setRunOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [employeeList, runResult] = await Promise.all([
        listEmployees({ pageSize: 100 }),
        listPayrollRuns({ pageSize: 1 }),
      ]);
      setEmployees(employeeList.items);
      setHasRuns(runResult.items.length > 0);
      setStatus({ state: "ready" });
    } catch {
      setStatus({ state: "error", message: "Could not load your payroll setup." });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") return null;

  if (status.state === "error") return null;

  const hasCompensation = employees.some(
    (employee) => employee.activeCompensation != null,
  );

  const steps: SetupStep[] = [
    {
      key: "compensation",
      label: "Record compensation",
      description: "Set a monthly salary so employees can be paid.",
      done: hasCompensation,
      action: canWrite
        ? {
            label: "Record",
            onClick: () => {
              setRunOpen(false);
              setCompensationOpen(true);
            },
          }
        : undefined,
    },
    {
      key: "runs",
      label: "Create a payroll run",
      description: "Open a pay period to compute, approve, and pay.",
      done: hasRuns,
      action: canWrite
        ? {
            label: "New run",
            onClick: () => {
              setCompensationOpen(false);
              setRunOpen(true);
            },
          }
        : undefined,
    },
    {
      key: "settings",
      label: "Tune payroll settings",
      description: "Currency, tax, provident fund, and rounding rules.",
      checkable: false,
      action: { label: "Open", href: "/dashboard/erp/payroll/settings" },
    },
  ];

  return (
    <>
      <SetupChecklist
        title="Get payroll set up"
        description="Set the basics before your first run."
        steps={steps}
      />
      <CompensationDialog
        open={compensationOpen}
        onOpenChange={setCompensationOpen}
        employees={employees}
        picker
        onSaved={() => void load()}
      />
      <NewRunDialog
        open={runOpen}
        onOpenChange={setRunOpen}
        onSaved={() => void load()}
      />
    </>
  );
}
