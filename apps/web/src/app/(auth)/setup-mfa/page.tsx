import type { Metadata } from "next";
import Link from "next/link";

import { MfaSetupStep } from "@/features/onboarding/mfa-setup-step";
import { AuthButton } from "@/lib/auth/AuthButton";

export const metadata: Metadata = {
  title: "Set up two-factor authentication",
  description: "Secure your account with an authenticator app.",
};

export default async function SetupMfaPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string }>;
}) {
  const params = await searchParams;
  const email = params.email?.trim();

  if (!email) {
    return (
      <div className="space-y-4 text-center">
        <div className="space-y-2">
          <h1 className="font-display text-2xl font-semibold text-foreground">
            Session expired
          </h1>
          <p className="text-sm text-muted-foreground">
            Complete onboarding to set up two-factor authentication.
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
          Final step
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Protect your account
        </h1>
        <p className="text-sm text-muted-foreground">
          Add an authenticator app to make sure only you can sign in.
        </p>
      </div>

      <MfaSetupStep />
    </div>
  );
}
