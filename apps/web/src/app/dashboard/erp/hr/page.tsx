import Link from "next/link";
import { ArrowRight, Building2, CalendarDays, UserRound, Users } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { HrOverview } from "./hr-overview";

const areas = [
  {
    href: "/dashboard/erp/hr/employees",
    title: "Employees",
    description: "Hire, update, and manage everyone on the team.",
    icon: UserRound,
  },
  {
    href: "/dashboard/erp/hr/departments",
    title: "Departments",
    description: "Structure teams and assign managers.",
    icon: Building2,
  },
  {
    href: "/dashboard/erp/hr/leave",
    title: "Leave",
    description: "Requests, approvals, and balances.",
    icon: CalendarDays,
  },
];

export default function HrHomePage() {
  return (
    <ModuleAccessBoundary module="erp" permission="erp.hr.read">
      <div className="space-y-6">
        <PageHeader
          title="HR"
          description="The people behind the business — employees, departments, and leave."
          icon={Users}
        />
        <HrOverview />
        <section className="space-y-3">
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            Explore
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {areas.map((area) => (
            <Link
              key={area.href}
              href={area.href}
              className="group relative flex flex-col rounded-xl border border-border bg-card p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-muted/40 active:translate-y-0"
            >
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
                <area.icon aria-hidden="true" className="size-5" />
              </div>
              <h3 className="mt-4 font-display text-base font-semibold text-foreground">
                {area.title}
              </h3>
              <p className="mt-1 flex-1 text-sm leading-relaxed text-muted-foreground">
                {area.description}
              </p>
              <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                Open
                <ArrowRight
                  aria-hidden="true"
                  className="size-4 transition-transform duration-200 group-hover:translate-x-0.5"
                />
              </span>
            </Link>
          ))}
          </div>
        </section>
      </div>
    </ModuleAccessBoundary>
  );
}
