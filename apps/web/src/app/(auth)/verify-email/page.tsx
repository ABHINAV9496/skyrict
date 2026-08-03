import type { Metadata } from "next";

import { VerifyEmailForm } from "@/features/auth/verify-email-form";

export const metadata: Metadata = {
  title: "Verify email",
  description: "Confirm your email address to activate your Skyrict account.",
};

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Account activation
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          {token ? "Confirming your email" : "Verify your email"}
        </h1>
      </div>

      <VerifyEmailForm token={token} />
    </div>
  );
}
