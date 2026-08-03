"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, KeyRound, Lock, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { demoSessionKey } from "@/config";
import { loginEmailPassword, verifyMfa } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { AuthInput } from "@/lib/auth/AuthInput";
import { OtpInput } from "@/lib/auth/OtpInput";

const credentialsSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});

type CredentialsValues = z.infer<typeof credentialsSchema>;

function LoginForm() {
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
    const result = await loginEmailPassword(values);
    if (result.status === "mfa_required") {
      setMfaToken(result.mfaToken);
      setSessionEmail(values.email);
      setStep("mfa");
      return;
    }
    if (result.status === "email_unverified") {
      setGenericError(
        "This account hasn't been verified yet. Check your inbox for the verification link.",
      );
      return;
    }
    setSessionEmail(values.email);
    localStorage.setItem(demoSessionKey, "1");
    setStep("success");
  }

  async function onSubmitMfa() {
    if (mfaCode.length !== 6 || !mfaToken) {
      setMfaError(true);
      return;
    }
    setMfaError(false);
    const result = await verifyMfa({ code: mfaCode, mfaToken });
    if (result.status === "ok") {
      localStorage.setItem(demoSessionKey, "1");
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
            Welcome back{sessionEmail ? `, ${sessionEmail}` : ""}
            {". This is a simulated sign-in \n the real API hasn't been wired yet."}
          </p>
        </div>
        <div className="space-y-2">
          <Link href="/dashboard/agents" className="block">
            <AuthButton className="w-full">Continue to workspace</AuthButton>
          </Link>
          <Link
            href="/marketing"
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
      <div className="space-y-1.5">
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
        <div className="flex justify-end pt-0.5">
          <Link
            href="/auth/forgot-password"
            className="text-sm text-primary underline-offset-4 hover:underline"
          >
            Forgot password?
          </Link>
        </div>
      </div>
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
      <p className="flex items-center justify-center gap-1.5 text-center text-sm text-muted-foreground">
        <KeyRound aria-hidden="true" className="size-3.5" />
        Argon2id hashing · TOTP available on your account
      </p>
    </form>
  );
}

export { LoginForm };
