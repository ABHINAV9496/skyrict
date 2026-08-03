import type { Metadata } from "next";

import { MfaVerifyForm } from "@/features/auth/mfa-verify-form";

export const metadata: Metadata = {
  title: "Two-factor check",
  description: "Confirm your identity with two-factor authentication.",
};

export default async function MfaVerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ mfaToken?: string }>;
}) {
  const { mfaToken } = await searchParams;

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Security
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Two-factor authentication
        </h1>
        <p className="text-sm text-muted-foreground">
          Confirm it&apos;s really you.
        </p>
      </div>

      <MfaVerifyForm mfaToken={mfaToken} />
    </div>
  );
}
