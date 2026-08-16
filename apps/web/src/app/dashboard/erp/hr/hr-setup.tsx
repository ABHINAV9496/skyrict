"use client";

import { useCallback, useEffect, useState } from "react";

import { EmployeeFormDialog } from "@/components/dashboard/erp/hr/employee-dialogs";
import { DepartmentDialog } from "@/components/dashboard/erp/hr/department-dialog";
import {
  SetupChecklist,
  type SetupStep,
} from "@/components/dashboard/shared/setup-checklist";
import { useModuleAccess } from "@/lib/access/modules";
import {
  listDepartments,
  listEmployees,
  listLeaveRequests,
  type Department,
  type Employee,
} from "@/lib/api/hr-api";

type LoadState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready" };

export function HrSetup() {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.hr.write");

  const [status, setStatus] = useState<LoadState>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [hasLeaveRequests, setHasLeaveRequests] = useState(false);

  const [hireOpen, setHireOpen] = useState(false);
  const [departmentOpen, setDepartmentOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [employeeList, departmentList, leaveResult] = await Promise.all([
        listEmployees({ pageSize: 50 }),
        listDepartments(),
        listLeaveRequests({ pageSize: 1 }),
      ]);
      setEmployees(employeeList.items);
      setDepartments(departmentList);
      setHasLeaveRequests(leaveResult.items.length > 0);
      setStatus({ state: "ready" });
    } catch {
      setStatus({ state: "error", message: "Could not load your HR setup." });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") return null;

  if (status.state === "error") return null;

  const activeEmployees = employees.filter(
    (employee) => employee.employmentStatus === "active",
  ).length;

  const steps: SetupStep[] = [
    {
      key: "employees",
      label: "Hire your first employee",
      description: `Add your team so you can assign work, leave, and pay.`,
      done: activeEmployees >= 1,
      action: canWrite
        ? {
            label: "Hire",
            onClick: () => {
              setDepartmentOpen(false);
              setHireOpen(true);
            },
          }
        : undefined,
    },
    {
      key: "departments",
      label: "Create a department",
      description: "Structure your team into groups with managers.",
      done: departments.length >= 1,
      action: canWrite
        ? {
            label: "Add",
            onClick: () => {
              setHireOpen(false);
              setDepartmentOpen(true);
            },
          }
        : undefined,
    },
    {
      key: "leave",
      label: "Track a leave request",
      description: "Approve and manage time off for your team.",
      done: hasLeaveRequests,
      action: canWrite
        ? { label: "Set up", href: "/dashboard/erp/hr/leave" }
        : undefined,
    },
  ];

  return (
    <>
      <SetupChecklist
        title="Get HR set up"
        description="A few steps to get payroll-ready."
        steps={steps}
      />
      <EmployeeFormDialog
        open={hireOpen}
        onOpenChange={setHireOpen}
        departments={departments}
        employee={null}
        onSaved={() => void load()}
      />
      <DepartmentDialog
        open={departmentOpen}
        onOpenChange={setDepartmentOpen}
        employees={employees}
        department={null}
        onSaved={() => void load()}
      />
    </>
  );
}
