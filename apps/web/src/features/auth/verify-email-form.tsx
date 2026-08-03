"use client";

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  Mail,
  MailCheck,
} from "lucide-react";
import Link from "next/link";

import { resendVerificationEmail, verifyEmail } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { AuthInput } from "@/lib/auth/AuthInput";

const resendSchema = z.object({
  email: z.string().email("Enter a valid email address"),
});

type ResendValues = z.infer<typeof resendSchema>;

type VerifyStatus = "verifying" | "verified" | "invalid";

function VerifyEmailForm({ token }: { token?: string }) {
  const ran = useRef(false);
  const [status, setStatus] = useState<VerifyStatus>(() =>
    token ? "verifying" : "verified",
  );
  const [sentEmail, setSentEmail] = useState<string>();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResendValues>({
    resolver: zodResolver(resendSchema),
    defaultValues: { email: "" },
  });

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    let cancelled = false;
    verifyEmail({ token }).then((result) => {
      if (cancelled) return;
      setStatus(result.status === "verified" ? "verified" : "invalid");
    });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function onSubmit(values: ResendValues) {
    const result = await resendVerificationEmail({ email: values.email });
    if (result.status === "sent") setSentEmail(result.email);
  }

  if (token && status === "verifying") {
    return (
      <div className="space-y-6 text-center">
        <LoaderCircle
          aria-hidden="true"
          className="mx-auto size-8 animate-spin text-primary"
        />
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            {"Verifying your email\n"}
          </h2>
          <p className="text-sm text-muted-foreground">
            Confirming the link from your inbox.
          </p>
        </div>
      </div>
    );
  }

  if (token && status === "invalid") {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle aria-hidden="true" className="size-6 text-destructive" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Link invalid or expired
          </h2>
          <p className="text-sm text-muted-foreground">
            This verification link is no longer valid. Request a fresh one and
            use the exact URL from the email.
          </p>
        </div>
        <div className="space-y-2">
          <Link href="/verify-email" className="block">
            <AuthButton className="w-full">Resend verification</AuthButton>
          </Link>
          <Link
            href="/login"
            className="block text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  if (token && status === "verified") {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/20">
          <CheckCircle2 aria-hidden="true" className="size-6 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Email verified
          </h2>
          <p className="text-sm text-muted-foreground">
            Your account is now fully activated. You can sign in and start using
            Skyrict.
          </p>
        </div>
        <Link href="/login" className="block">
          <AuthButton className="w-full">Sign in</AuthButton>
        </Link>
      </div>
    );
  }

  if (sentEmail) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/20">
          <MailCheck aria-hidden="true" className="size-6 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Verification email sent
          </h2>
          <p className="text-sm text-muted-foreground">
            A fresh link is on its way to{" "}
            <span className="font-medium text-foreground">{sentEmail}</span>.
          </p>
        </div>
        <Link href="/login" className="block">
          <AuthButton className="w-full">Back to sign in</AuthButton>
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
      <p className="text-sm text-muted-foreground">
        Enter the email you registered with and we&apos;ll send you a fresh
        verification link.
      </p>
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
      <AuthButton type="submit" className="w-full" loading={isSubmitting}>
        Send verification email
      </AuthButton>
      <div className="text-center">
        <Link
          href="/login"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          Back to sign in
        </Link>
      </div>
    </form>
  );
}

export { VerifyEmailForm };
