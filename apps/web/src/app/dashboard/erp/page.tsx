import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  Blocks,
  Contact,
  Package,
  Receipt,
  ShoppingCart,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { DigestCard } from "@/components/dashboard/erp/digest-card";
import { ErpOverviewSummary } from "@/components/dashboard/erp/erp-overview-summary";
import { PageHeader } from "@/components/dashboard/shared/page-header";

const quickLinks: {
  href: string;
  title: string;
  description: string;
  icon: LucideIcon;
}[] = [
  { href: "/dashboard/erp/crm/overview", title: "CRM", description: "Leads, pipelines, and customers.", icon: Contact },
  { href: "/dashboard/erp/orders", title: "Orders", description: "Sales orders and the fulfilment flow.", icon: ShoppingCart },
  { href: "/dashboard/erp/inventory", title: "Inventory", description: "Stock and warehouses.", icon: Package },
  { href: "/dashboard/erp/finance", title: "Finance", description: "Cash flow and ledgers.", icon: Wallet },
  { href: "/dashboard/erp/hr", title: "HR", description: "People and the team.", icon: Users },
  { href: "/dashboard/erp/payroll", title: "Payroll", description: "Runs, compensation, and pay rules.", icon: Receipt },
  { href: "/dashboard/erp/reports", title: "Reports", description: "Dashboards and exports.", icon: BarChart3 },
];

export default function ErpPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Business Operations"
        description="Operations management — inventory, sales, cash, and orders, all on one source of truth."
        icon={Blocks}
      />

      <section className="space-y-4">
        <DigestCard />
      </section>

      <section className="space-y-4">
        <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
          At a glance
        </h2>
        <ErpOverviewSummary />
      </section>

      <section className="space-y-4">
        <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
          Modules
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {quickLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="group relative flex flex-col rounded-xl border border-border bg-card p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-muted/40 active:translate-y-0"
            >
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
                <link.icon aria-hidden="true" className="size-5" />
              </div>
              <h3 className="mt-4 font-display text-base font-semibold text-foreground">
                {link.title}
              </h3>
              <p className="mt-1 flex-1 text-sm leading-relaxed text-muted-foreground">
                {link.description}
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
  );
}
