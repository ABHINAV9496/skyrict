"use client";

import { useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { demoSessionKey } from "@/config";
import { verifyMfa } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { OtpInput } from "@/lib/auth/OtpInput";

function MfaVerifyForm({ mfaToken }: { mfaToken?: string }) {
  const [useBackup, setUseBackup] = useState(false);
  const [code, setCode] = useState("");
  const [backupCode, setBackupCode] = useState("");
  const [error, setError] = useState(false);
  const [done, setDone] = useState(false);

  const codeReady = useBackup
    ? backupCode.replace(/\D/g, "").length === 10
    : code.length === 6;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!codeReady) return;
    setError(false);
    const result = await verifyMfa({
      code: useBackup ? backupCode : code,
      mfaToken: mfaToken ?? "demo-mfa-token",
      isBackupCode: useBackup,
    });
    if (result.status === "ok") {
      localStorage.setItem(demoSessionKey, "1");
      setDone(true);
    } else {
      setError(true);
      setCode("");
      setBackupCode("");
    }
  }

  if (done) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/20">
          <CheckCircle2 aria-hidden="true" className="size-6 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="font-display text-2xl font-semibold text-foreground">
            Verified
          </h2>
          <p className="text-sm text-muted-foreground">
            {"Two-factor authentication passed. This is a simulated check \n the real API hasn't been wired yet."}
          </p>
        </div>
        <Link href="/dashboard/agents" className="block">
          <AuthButton className="w-full">Continue to workspace</AuthButton>
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <div className="flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/15">
          <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
        </div>
        <div className="space-y-1">
          <h2 className="font-display text-lg font-semibold text-foreground">
            Two-factor check
          </h2>
          <p className="text-sm text-muted-foreground">
            {useBackup
              ? "Enter one of your backup codes. Each code works once."
              : "Enter the 6-digit code from your authenticator app."}
          </p>
        </div>
      </div>
      {useBackup ? (
        <input
          value={backupCode}
          onChange={(event) =>
            setBackupCode(event.target.value.replace(/[^a-z0-9]/gi, ""))
          }
          placeholder="XXXXX-XXXXX"
          aria-label="Backup code"
          aria-invalid={error}
          autoComplete="one-time-code"
          className="h-14 w-full rounded-lg border border-border bg-card px-4 text-center font-mono text-lg uppercase tracking-widest tabular-nums outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
        />
      ) : (
        <OtpInput value={code} onChange={setCode} error={error} />
      )}
      {error ? (
        <p className="text-sm font-medium text-destructive">
          That code didn&apos;t match. Try again.
        </p>
      ) : null}
      <AuthButton
        type="submit"
        className="w-full"
        loading={false}
        disabled={!codeReady}
      >
        Verify
      </AuthButton>
      <button
        type="button"
        onClick={() => {
          setUseBackup((value) => !value);
          setError(false);
        }}
        className="w-full text-center text-sm text-muted-foreground underline-offset-4 hover:underline"
      >
        {useBackup ? "Use authenticator code" : "Use a backup code"}
      </button>
    </form>
  );
}

export { MfaVerifyForm };
