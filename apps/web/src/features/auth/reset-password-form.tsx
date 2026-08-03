"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";

import { confirmPasswordReset } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { AuthInput } from "@/lib/auth/AuthInput";
import { PasswordStrength } from "@/lib/auth/PasswordStrength";

const resetSchema = z
  .object({
    password: z.string().min(8, "Use at least 8 characters"),
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ["confirmPassword"],
  });

type ResetValues = z.infer<typeof resetSchema>;

function ResetPasswordForm({ token }: { token?: string }) {
  const [done, setDone] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: "", confirmPassword: "" },
  });

  const password = watch("password");

  async function onSubmit(values: ResetValues) {
    if (!token) return;
    await confirmPasswordReset({ token, newPassword: values.password });
    setDone(true);
  }

  if (!token) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle aria-hidden="true" className="size-6 text-destructive" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Invalid reset link
          </h2>
          <p className="text-sm text-muted-foreground">
            This link is missing or malformed. Request a fresh one and use the
            exact URL from the email.
          </p>
        </div>
        <div className="space-y-2">
          <Link href="/auth/forgot-password" className="block">
            <AuthButton className="w-full">Request a new link</AuthButton>
          </Link>
          <Link
            href="/auth/login"
            className="block text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/20">
          <CheckCircle2 aria-hidden="true" className="size-6 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Password updated
          </h2>
          <p className="text-sm text-muted-foreground">
            Your password has been reset. Sign in with your new credentials.
          </p>
        </div>
        <div className="space-y-2">
          <Link href="/auth/login" className="block">
            <AuthButton className="w-full">Sign in</AuthButton>
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

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
      <p className="text-sm text-muted-foreground">
        Choose a new password. It must be at least 8 characters.
      </p>
      <div className="space-y-1.5">
        <AuthInput
          label="New password"
          id="password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 8 characters"
          error={errors.password?.message}
          {...register("password")}
        />
        <PasswordStrength password={password} />
      </div>
      <AuthInput
        label="Confirm new password"
        id="confirmPassword"
        type="password"
        autoComplete="new-password"
        placeholder="Repeat your password"
        error={errors.confirmPassword?.message}
        {...register("confirmPassword")}
      />
      <AuthButton type="submit" className="w-full" loading={isSubmitting}>
        Reset password
      </AuthButton>
    </form>
  );
}

export { ResetPasswordForm };
