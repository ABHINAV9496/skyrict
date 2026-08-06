"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Lock, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { loginEmailPassword, verifyMfa } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { AuthInput } from "@/lib/auth/AuthInput";
import { OtpInput } from "@/lib/auth/OtpInput";
import { TrustIndicator } from "@/lib/auth/TrustIndicator";

const credentialsSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});

type CredentialsValues = z.infer<typeof credentialsSchema>;

function LoginForm() {
  const router = useRouter();
  const [step, setStep] = useState<"credentials" | "mfa" | "success">(
    "credentials",
  );
  const [genericError, setGenericError] = useState<string>();
  const [mfaToken, setMfaToken] = useState<string>();
  const [sessionEmail, setSessionEmail] = useState<string>();
  const [mfaCode, setMfaCode] = useState("");
  const [mfaError, setMfaError] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<CredentialsValues>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { email: "", password: "" },
  });

  async function onSubmitCredentials(values: CredentialsValues) {
    setGenericError(undefined);
    try {
      const result = await loginEmailPassword(values);
      if (result.status === "mfa_challenge") {
        setMfaToken(result.mfaToken);
        setSessionEmail(result.user.email);
        setMfaCode("");
        setMfaError(false);
        setStep("mfa");
        return;
      }
      setSessionEmail(values.email);
      if (result.status === "mfa_setup") {
        const next = new URLSearchParams({ email: values.email.trim() });
        router.push(`/setup-mfa?${next.toString()}`);
        return;
      }
      setStep("success");
    } catch (err) {
      setGenericError(
        err instanceof Error
          ? err.message
          : "Unable to sign in. Check your credentials and try again.",
      );
    }
  }

  async function onSubmitMfa() {
    if (mfaCode.length !== 6 || !mfaToken) {
      setMfaError(true);
      return;
    }
    setMfaError(false);
    const result = await verifyMfa({ code: mfaCode, mfaToken });
    if (result.status === "ok") {
      setStep("success");
    } else {
      setMfaError(true);
      setMfaCode("");
    }
  }

  if (step === "success") {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/20">
          <CheckCircle2 aria-hidden="true" className="size-6 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            You&apos;re signed in
          </h2>
          <p className="text-sm text-muted-foreground">
            Welcome back{sessionEmail ? `, ${sessionEmail}` : ""}.
          </p>
        </div>
        <div className="space-y-2">
          <Link href="/dashboard/agents" className="block">
            <AuthButton className="w-full">Continue to workspace</AuthButton>
          </Link>
          <Link
            href="/"
            className="block text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Back to home
          </Link>
        </div>
      </div>
    );
  }

  if (step === "mfa") {
    return (
      <div className="space-y-6">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/15">
            <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
          </div>
          <div className="space-y-1">
            <h2 className="font-display text-lg font-semibold text-foreground">
              Two-factor check
            </h2>
            <p className="text-sm text-muted-foreground">
              Enter the 6-digit code from your authenticator app.
            </p>
          </div>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void onSubmitMfa();
          }}
          className="space-y-6"
        >
          <OtpInput
            value={mfaCode}
            onChange={setMfaCode}
            error={mfaError}
            ariaLabel="Two-factor code"
          />
          {mfaError ? (
            <p className="text-sm font-medium text-destructive">
              That code didn&apos;t match. Try again or use a backup code.
            </p>
          ) : null}
          <AuthButton
            type="submit"
            className="w-full"
            loading={false}
            disabled={mfaCode.length !== 6}
          >
            Verify code
          </AuthButton>
          <button
            type="button"
            onClick={() => {
              setStep("credentials");
              setMfaCode("");
              setMfaError(false);
            }}
            className="w-full text-center text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Back to sign in
          </button>
        </form>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmitCredentials)}
      className="space-y-5"
      noValidate
    >
      <AuthInput
        label="Email"
        id="email"
        type="email"
        autoComplete="email"
        placeholder="you@company.com"
        icon={Mail}
        error={errors.email?.message}
        {...register("email")}
      />
      <AuthInput
        label="Password"
        id="password"
        type="password"
        autoComplete="current-password"
        placeholder={"\n"}
        icon={Lock}
        error={errors.password?.message}
        {...register("password")}
      />
      {genericError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
        >
          {genericError}
        </div>
      ) : null}
      <AuthButton type="submit" className="w-full" loading={isSubmitting}>
        Sign in
      </AuthButton>
      <TrustIndicator />
    </form>
  );
}

export { LoginForm };
