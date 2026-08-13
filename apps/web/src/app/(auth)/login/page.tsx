import type { Metadata } from "next";

import { LoginForm } from "@/features/auth/login-form";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to your Skyrict workspace.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; error?: string; accepted?: string }>;
}) {
  const params = await searchParams;
  const email = params.email?.trim() ?? "";
  const error = params.error?.trim() ?? "";
  const accepted = params.accepted === "1";

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Welcome back
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Sign in to Skyrict
        </h1>
        <p className="text-sm text-muted-foreground">
          Enter your credentials to access your workspace.
        </p>
      </div>

      <LoginForm initialEmail={email} initialError={error} accepted={accepted} />
    </div>
  );
}
