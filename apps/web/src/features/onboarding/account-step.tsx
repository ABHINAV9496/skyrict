"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, LoaderCircle, Mail } from "lucide-react";

import { RiskChallenge } from "@/components/onboarding/risk-challenge";
import { checkEmailAvailability } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { AuthInput } from "@/lib/auth/AuthInput";

const emailSchema = z.string().trim().email("Enter a valid email address");

const accountSchema = z.object({
  email: emailSchema,
});

type AccountValues = z.infer<typeof accountSchema>;

function AccountStep({ demoCaptcha = false }: { demoCaptcha?: boolean }) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [captchaVisible, setCaptchaVisible] = useState(false);
  const [captchaValid, setCaptchaValid] = useState(false);
  const [captchaError, setCaptchaError] = useState(false);
  const [availability, setAvailability] = useState<
    "idle" | "checking" | "available" | "taken"
  >("idle");
  const {
    register,
    handleSubmit,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AccountValues>({
    resolver: zodResolver(accountSchema),
    defaultValues: { email: "" },
  });

  const email = watch("email");

  useEffect(() => {
    let cancelled = false;
    const parsed = emailSchema.safeParse(email);
    if (!parsed.success) {
      setAvailability("idle");
      return;
    }
    setAvailability("checking");
    const timer = setTimeout(async () => {
      const result = await checkEmailAvailability({ email: parsed.data });
      if (!cancelled) {
        setAvailability(result.available ? "available" : "taken");
      }
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [email]);

  async function onSubmit(values: AccountValues) {
    const honeypot = new FormData(formRef.current ?? undefined).get("website");
    if (typeof honeypot === "string" && honeypot.length > 0) {
      return;
    }
    const result = await checkEmailAvailability({ email: values.email });
    if (!result.available) {
      setError("email", {
        type: "manual",
        message: "This email is already registered. Try signing in instead.",
      });
      return;
    }
    if (captchaVisible && !captchaValid) {
      setCaptchaError(true);
      return;
    }
    const next = new URLSearchParams({ email: values.email.trim() });
    router.push(`/register/verify?${next.toString()}`);
  }

  return (
    <form
      ref={formRef}
      onSubmit={handleSubmit(onSubmit)}
      className="space-y-4"
      noValidate
    >
      <AuthInput
        label="Work email"
        id="email"
        type="email"
        autoComplete="email"
        placeholder="you@company.com"
        icon={Mail}
        hint={
          availability === "checking"
            ? "Checking availability\n"
            : availability === "available"
              ? "This email is available."
              : undefined
        }
        error={
          errors.email?.message ??
          (availability === "taken"
            ? "This email is already registered. Try signing in instead."
            : undefined)
        }
        trailing={
          availability === "checking" ? (
            <LoaderCircle
              aria-hidden="true"
              className="mr-1 size-4 animate-spin text-muted-foreground"
            />
          ) : availability === "available" ? (
            <CheckCircle2 aria-hidden="true" className="mr-1 size-4 text-primary" />
          ) : null
        }
        {...register("email")}
      />

      <div className="pt-1">
        <RiskChallenge
          demoCaptcha={demoCaptcha}
          onShowChange={setCaptchaVisible}
          onValidChange={(valid) => {
            setCaptchaValid(valid);
            if (valid) setCaptchaError(false);
          }}
        />
        {captchaError && captchaVisible ? (
          <p className="mt-1.5 text-xs font-medium text-destructive">
            Confirm you&apos;re not a robot to continue.
          </p>
        ) : null}
      </div>

      <AuthButton type="submit" className="w-full" loading={isSubmitting}>
        Continue
      </AuthButton>
    </form>
  );
}

export { AccountStep };
