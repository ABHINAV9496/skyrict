"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound } from "lucide-react";

import { CaptchaChallenge } from "@/components/onboarding/captcha-challenge";
import { completeSecurityStep } from "@/lib/api/auth-api";
import { AuthInput } from "@/lib/auth/AuthInput";
import { AuthButton } from "@/lib/auth/AuthButton";
import { PasswordField } from "@/lib/auth/PasswordField";
import { PasswordRequirements } from "@/lib/auth/PasswordRequirements";
import { PasswordStrength } from "@/lib/auth/PasswordStrength";
import { allRequirementsMet } from "@/lib/auth/password";

const securitySchema = z
  .object({
    password: z
      .string()
      .min(12, "Use at least 12 characters")
      .refine(
        (value) => allRequirementsMet(value),
        "Meet every requirement to continue.",
      ),
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ["confirmPassword"],
  });

type SecurityValues = z.infer<typeof securitySchema>;

function SecurityStep({
  email,
  vt,
}: {
  email: string;
  vt: string;
}) {
  const router = useRouter();

  const [captchaValid, setCaptchaValid] = useState(false);
  const [captchaError, setCaptchaError] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<SecurityValues>({
    resolver: zodResolver(securitySchema),
    defaultValues: { password: "", confirmPassword: "" },
  });

  const password = watch("password");

  function onSubmit(values: SecurityValues) {
    if (!captchaValid) {
      setCaptchaError(true);
      return;
    }
    completeSecurityStep({
      email,
      verificationToken: vt,
      password: values.password,
    }).then(() => {
      const next = new URLSearchParams({ email, vt });
      router.push(`/onboarding/register/plan?${next.toString()}`);
    });
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <PasswordField
          label="Password"
          id="password"
          autoComplete="new-password"
          placeholder="12+ characters"
          icon={KeyRound}
          error={errors.password?.message}
          {...register("password")}
        />
        <PasswordStrength password={password} />
        <PasswordRequirements password={password} />
      </div>

      <AuthInput
        label="Confirm password"
        id="confirmPassword"
        type="password"
        autoComplete="new-password"
        placeholder="Repeat your password"
        error={errors.confirmPassword?.message}
        {...register("confirmPassword")}
      />

      <div className="space-y-1.5 pt-1">
        <CaptchaChallenge
          onValidChange={(valid) => {
            setCaptchaValid(valid);
            if (valid) setCaptchaError(false);
          }}
        />
        {captchaError ? (
          <p className="text-xs font-medium text-destructive">
            Enter the code shown above to continue.
          </p>
        ) : null}
      </div>

      <AuthButton type="submit" className="w-full" loading={isSubmitting}>
        Continue
      </AuthButton>
    </form>
  );
}

export { SecurityStep };
