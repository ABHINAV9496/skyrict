import type { Metadata } from "next";
import Link from "next/link";

import { AccountStep } from "@/features/onboarding/account-step";

export const metadata: Metadata = {
  title: "Create your workspace",
  description: "Step 1 of 5 — enter your work email to start.",
};

export default async function RegisterPage({
  searchParams,
}: {
  searchParams: Promise<{ demoCaptcha?: string }>;
}) {
  const params = await searchParams;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Step 1 of 5 · Account
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Let&apos;s get you set up
        </h1>
        <p className="text-sm text-muted-foreground">
          Create your Skyrict account in about two minutes. We&apos;ll confirm
          your email, secure your password, pick a plan, and connect your
          organization.
        </p>
      </div>

      <AccountStep demoCaptcha={params.demoCaptcha === "1"} />

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link
          href="/auth/login"
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
