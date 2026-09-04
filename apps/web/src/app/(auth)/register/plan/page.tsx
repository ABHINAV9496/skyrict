import type { Metadata } from "next";
import Link from "next/link";

import { PlanStep } from "@/features/onboarding/plan-step";
import { AuthButton } from "@/lib/auth/AuthButton";

export const metadata: Metadata = {
  title: "Choose a plan",
  description: "Step 4 of 5 - pick the plan that fits your business.",
};

export default async function PlanPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; vt?: string }>;
}) {
  const params = await searchParams;
  const email = params.email?.trim();
  const vt = params.vt?.trim();

  if (!email || !vt) {
    return (
      <div className="space-y-4 text-center">
        <div className="space-y-2">
          <h1 className="font-display text-2xl font-semibold text-foreground">
            Session expired
          </h1>
          <p className="text-sm text-muted-foreground">
            Your verification session is missing. Restart the flow to continue.
          </p>
        </div>
        <Link href="/register" className="block">
          <AuthButton className="w-full">Start over</AuthButton>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Step 4 of 5 · Plan
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Choose your plan
        </h1>
        <p className="text-sm text-muted-foreground">
          Start free and upgrade as your business grows. You can change plans
          anytime.
        </p>
      </div>

      <PlanStep email={email} vt={vt} />
    </div>
  );
}
