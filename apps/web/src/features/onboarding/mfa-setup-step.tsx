"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  Copy,
  KeyRound,
  LoaderCircle,
  QrCode,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { confirmMfaSetup, setupMfa, type MfaSetup } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { OtpInput } from "@/lib/auth/OtpInput";
import { cn } from "@/lib/utils";

function MfaSetupStep() {
  const router = useRouter();
  const [setup, setSetup] = useState<MfaSetup>();
  const [code, setCode] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string>();
  const [copied, setCopied] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setupMfa()
      .then((result) => {
        if (!cancelled) setSetup(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not start MFA setup. Try again.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function copySecret() {
    if (!setup) return;
    await navigator.clipboard.writeText(setup.secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function confirm() {
    if (!setup) return;
    if (code.length !== 6) {
      setError("Enter the 6-digit code from your authenticator app.");
      return;
    }
    setConfirming(true);
    setError(undefined);
    const result = await confirmMfaSetup({ code });
    setConfirming(false);
    if (result.status === "ok") {
      setConfirmed(true);
    } else {
      setCode("");
      setError("That code doesn't match. Try again.");
    }
  }

  function finish() {
    router.push("/dashboard/agents");
  }

  if (!setup) {
    if (error) {
      return (
        <div className="space-y-4 py-8 text-center">
          <p className="text-sm font-medium text-destructive">{error}</p>
          <AuthButton
            type="button"
            className="w-full"
            onClick={() => window.location.reload()}
          >
            Try again
          </AuthButton>
        </div>
      );
    }
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
        {"Preparing your authenticator enrollment\n"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3 rounded-lg border border-primary/40 bg-primary/10 p-4">
        <ShieldCheck
          aria-hidden="true"
          className="mt-0.5 size-5 shrink-0 text-primary"
        />
        <div className="space-y-1 text-sm">
          <p className="font-medium text-foreground">Mandatory for your security</p>
          <p className="text-xs text-muted-foreground">
            Two-factor authentication is required for every Skyrict workspace.
            You&apos;ll need it the next time you sign in.
          </p>
        </div>
      </div>

      {!confirmed ? (
        <div className="space-y-5">
          <div className="rounded-xl border border-border bg-muted/40 p-4">
            <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
              <QrCode aria-hidden="true" className="size-4 text-primary" />
              Step 1 · Scan with your authenticator app
            </p>
            <div className="mx-auto mt-4 flex size-40 items-center justify-center rounded-xl border border-border bg-white p-2">
              <QRCodeSVG
                value={setup.otpauthUri}
                size={144}
                level="M"
                marginSize={0}
                aria-label="QR code to scan with your authenticator app"
              />
            </div>
            <p className="mt-3 text-center text-xs text-muted-foreground">
              Or add this key manually:
            </p>
            <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-border bg-card p-2.5">
              <code className="truncate font-mono text-xs text-foreground">
                {setup.secret}
              </code>
              <button
                type="button"
                onClick={copySecret}
                aria-label="Copy secret key"
                className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {copied ? (
                  <Check aria-hidden="true" className="size-4 text-primary" />
                ) : (
                  <Copy aria-hidden="true" className="size-4" />
                )}
              </button>
            </div>
          </div>

          <div className="space-y-3">
            <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
              <KeyRound aria-hidden="true" className="size-4 text-primary" />
              Step 2 · Enter the 6-digit code
            </p>
            <OtpInput
              length={6}
              value={code}
              onChange={setCode}
              disabled={confirming}
              error={Boolean(error)}
              ariaLabel="Authenticator code"
            />
            {error ? (
              <p className="text-center text-xs font-medium text-destructive">
                {error}
              </p>
            ) : (
              <p className="text-center text-xs text-muted-foreground">
                Open your authenticator app and scan the code to generate a
                6-digit code.
              </p>
            )}
            <AuthButton
              type="button"
              className="w-full"
              loading={confirming}
              onClick={confirm}
            >
              Verify and continue
            </AuthButton>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 p-3">
            <Check aria-hidden="true" className="size-4 text-primary" />
            <p className="text-sm font-medium text-foreground">
              Authenticator verified. Back up your recovery codes.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-muted/40 p-4">
            <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
              <ShieldAlert aria-hidden="true" className="size-4 text-primary" />
              Recovery codes
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Store these in a safe place. Each works once to sign in if you
              lose your authenticator app.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-1.5">
              {setup.backupCodes.map((backupCode) => (
                <code
                  key={backupCode}
                  className="rounded-md border border-border bg-card px-2 py-1.5 text-center font-mono text-xs text-foreground"
                >
                  {backupCode}
                </code>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={() => setAcknowledged((value) => !value)}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
              acknowledged
                ? "border-primary/50 bg-primary/10"
                : "border-border hover:border-primary/40",
            )}
            aria-pressed={acknowledged}
          >
            <span
              className={cn(
                "flex size-4 shrink-0 items-center justify-center rounded-[4px] border transition-colors",
                acknowledged
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-input bg-card",
              )}
            >
              {acknowledged ? (
                <Check aria-hidden="true" className="size-3" />
              ) : null}
            </span>
            I&apos;ve saved my recovery codes somewhere safe.
          </button>

          <AuthButton
            type="button"
            className="w-full"
            disabled={!acknowledged}
            onClick={finish}
          >
            Finish setup
          </AuthButton>
        </div>
      )}
    </div>
  );
}

export { MfaSetupStep };
