"use client";

import { useState } from "react";
import { LoaderCircle, ShieldCheck } from "lucide-react";

import { completeHandoff, verifyMfa } from "@/lib/api/auth-api";
import { AuthButton } from "@/lib/auth/AuthButton";
import { OtpInput } from "@/lib/auth/OtpInput";

function MfaVerifyForm({ mfaToken }: { mfaToken?: string }) {
  const [useBackup, setUseBackup] = useState(false);
  const [code, setCode] = useState("");
  const [backupCode, setBackupCode] = useState("");
  const [error, setError] = useState(false);
  const [handingOff, setHandingOff] = useState(false);

  const codeReady = useBackup
    ? backupCode.length === 16
    : code.length === 6;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!codeReady) return;
    setError(false);
    if (!mfaToken) {
      setError(true);
      return;
    }
    const result = await verifyMfa({
      code: useBackup ? backupCode : code,
      mfaToken: mfaToken,
    });
    if (result.status === "ok") {
      setHandingOff(true);
      await completeHandoff("/");
    } else {
      setError(true);
      setCode("");
      setBackupCode("");
    }
  }

  if (handingOff) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
        {"Opening your workspace\n"}
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
            setBackupCode(event.target.value.replace(/[^a-f0-9]/gi, "").toLowerCase())
          }
          placeholder="abcdef0123456789"
          aria-label="Backup code"
          aria-invalid={error}
          autoComplete="off"
          className="h-14 w-full rounded-lg border border-border bg-card px-4 text-center font-mono text-lg lowercase tracking-widest tabular-nums outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30"
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
