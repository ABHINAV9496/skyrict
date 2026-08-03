import type { Metadata } from "next";

import { ForgotPasswordForm } from "@/features/auth/forgot-password-form";

export const metadata: Metadata = {
  title: "Forgot password",
  description: "Request a password reset link for your Skyrict account.",
};

export default function ForgotPasswordPage() {
  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
          Account recovery
        </p>
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Forgot your password?
        </h1>
      </div>

      <ForgotPasswordForm />
    </div>
  );
}
