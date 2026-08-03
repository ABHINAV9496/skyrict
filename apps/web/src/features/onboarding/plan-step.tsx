"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { plans, type Plan, type PlanId } from "@/config/onboarding";
import { AuthButton } from "@/lib/auth/AuthButton";
import { cn } from "@/lib/utils";

type Billing = "monthly" | "annual";

function formatPrice(plan: Plan, billing: Billing): string {
  const price = billing === "annual" ? plan.annual : plan.monthly;
  if (price === null) return "Custom";
  if (price === 0) return "Free";
  return `$${price}`;
}

function PlanCard({
  plan,
  billing,
  selected,
  onSelect,
}: {
  plan: Plan;
  billing: Billing;
  selected: boolean;
  onSelect: () => void;
}) {
  const price = billing === "annual" ? plan.annual : plan.monthly;

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "relative w-full rounded-xl border bg-card p-3.5 text-left transition-all",
        "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 outline-none",
        selected
          ? "border-primary ring-3 ring-primary/15"
          : "border-border hover:border-primary/50",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display text-sm font-semibold text-foreground">
            {plan.name}
          </p>
          <p className="mt-0.5 line-clamp-2 text-xs leading-snug text-muted-foreground">
            {plan.tagline}
          </p>
        </div>
        <span
          className={cn(
            "flex size-4 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
            selected ? "border-primary bg-primary text-primary-foreground" : "border-border",
          )}
        >
          {selected ? <Check aria-hidden="true" className="size-3" /> : null}
        </span>
      </div>

      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-1.5">
        <span className="font-display text-lg font-semibold text-foreground">
          {formatPrice(plan, billing)}
        </span>
        {price !== null && price > 0 ? (
          <span className="text-[11px] text-muted-foreground">
            / user / month
          </span>
        ) : null}
      </div>
    </button>
  );
}

function CompareDialog() {
  return (
    <Dialog>
      <DialogTrigger className="text-sm font-medium text-primary underline-offset-4 hover:underline outline-none">
        Compare plans
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Compare plans</DialogTitle>
          <DialogDescription>
            Every plan includes email verification, MFA, and end-to-end
            encryption.
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr>
                <th className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
                  Feature
                </th>
                {plans.map((plan) => (
                  <th
                    key={plan.id}
                    className="border-b border-border px-3 py-2 text-center"
                  >
                    <span className="font-display text-sm font-semibold text-foreground">
                      {plan.name}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ["Price", (p: Plan) => formatPrice(p, "monthly")],
                ["Users", (p: Plan) => p.users],
                ["AI credits", (p: Plan) => p.aiCredits],
                ["Support", (p: Plan) => p.support],
              ].map(([label, render]) => (
                <tr key={String(label)}>
                  <td className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
                    {String(label)}
                  </td>
                  {plans.map((plan) => (
                    <td
                      key={plan.id}
                      className="border-b border-border px-3 py-2 text-center text-xs text-foreground"
                    >
                      {(render as (p: Plan) => string)(plan)}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
                  Highlights
                </td>
                {plans.map((plan) => (
                  <td
                    key={plan.id}
                    className="border-b border-border px-3 py-2 align-top"
                  >
                    <ul className="space-y-1.5 text-xs text-muted-foreground">
                      {plan.modules.map((module) => (
                        <li key={module} className="flex items-start gap-1.5">
                          <Check
                            aria-hidden="true"
                            className="mt-0.5 size-3 shrink-0 text-primary"
                          />
                          <span className="text-left">{module}</span>
                        </li>
                      ))}
                    </ul>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PlanStep({
  email,
  vt,
}: {
  email: string;
  vt: string;
}) {
  const router = useRouter();
  const [billing, setBilling] = useState<Billing>("annual");
  const [selected, setSelected] = useState<PlanId>("professional");

  function handleContinue() {
    const next = new URLSearchParams({ email, vt, plan: selected });
    router.push(`/onboarding/register/organization?${next.toString()}`);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center rounded-full border border-border bg-muted/40 p-1 text-xs font-medium">
          <button
            type="button"
            onClick={() => setBilling("monthly")}
            className={cn(
              "rounded-full px-3 py-1 transition-colors",
              billing === "monthly"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Monthly
          </button>
          <button
            type="button"
            onClick={() => setBilling("annual")}
            className={cn(
              "rounded-full px-3 py-1 transition-colors",
              billing === "annual"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Annual
          </button>
        </div>
        <CompareDialog />
      </div>

      <div
        className="grid grid-cols-2 items-stretch gap-3"
        role="radiogroup"
        aria-label="Select a plan"
      >
        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            billing={billing}
            selected={selected === plan.id}
            onSelect={() => setSelected(plan.id)}
          />
        ))}
      </div>

      <p className="text-center text-xs text-muted-foreground">
        Switch or cancel anytime. Prices shown in USD.
      </p>

      <AuthButton type="button" className="w-full" onClick={handleContinue}>
        Continue with {plans.find((p) => p.id === selected)?.name}
      </AuthButton>
    </div>
  );
}

export { PlanStep };
