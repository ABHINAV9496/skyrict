import type { Metadata } from "next";

import { MfaSetupStep } from "@/features/onboarding/mfa-setup-step";

export const metadata: Metadata = {
  title: "Set up two-factor authentication",
  description: "Secure your account with an authenticator app.",
};

export default function SetupMfaPage() {
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
