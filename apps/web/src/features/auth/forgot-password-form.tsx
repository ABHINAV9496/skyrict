"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Mail, MailCheck } from "lucide-react";
import Link from "next/link";

import { requestPasswordReset } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { AuthInput } from "@/lib/auth/AuthInput";

const forgotSchema = z.object({
  email: z.string().email("Enter a valid email address"),
});

type ForgotValues = z.infer<typeof forgotSchema>;

function ForgotPasswordForm() {
  const [sentEmail, setSentEmail] = useState<string>();
  const [error, setError] = useState<string>();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: "" },
  });

  async function onSubmit(values: ForgotValues) {
    setError(undefined);
    const result = await requestPasswordReset({ email: values.email });
    if (result.status === "sent") {
      setSentEmail(result.email);
    }
  }

  if (sentEmail) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/20">
          <MailCheck aria-hidden="true" className="size-6 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Check your inbox
          </h2>
          <p className="text-sm text-muted-foreground">
            If an account exists for{" "}
            <span className="font-medium text-foreground">{sentEmail}</span>, a
            password reset link is on its way. It expires in 30 minutes.
          </p>
          <p className="text-xs text-muted-foreground/80">
            {"This step is simulated \n no email was actually sent."}
          </p>
        </div>
        <div className="space-y-2">
          <Link href="/login" className="block">
            <AuthButton className="w-full">Back to sign in</AuthButton>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
      <p className="text-sm text-muted-foreground">
        Enter the email you signed up with and we&apos;ll send you a link to
        reset your password.
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
      {error ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {error}
        </p>
      ) : null}
      <AuthButton type="submit" className="w-full" loading={isSubmitting}>
        Send reset link
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

export { ForgotPasswordForm };
