"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, ShieldCheck, Sparkles } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { assessRisk, solveCaptcha } from "@/lib/api/auth-api";
import { cn } from "@/lib/utils";

function RiskChallenge({
  demoCaptcha = false,
  onValidChange,
  onShowChange,
}: {
  demoCaptcha?: boolean;
  onValidChange?: (valid: boolean) => void;
  onShowChange?: (visible: boolean) => void;
}) {
  const [show, setShow] = useState(false);
  const [state, setState] = useState<"idle" | "verifying" | "verified">(
    "idle",
  );
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    assessRisk().then((risk) => {
      if (cancelled) return;
      const visible = risk.requiresCaptcha || demoCaptcha;
      setShow(visible);
      onShowChange?.(visible);
    });
    return () => {
      cancelled = true;
    };
  }, [demoCaptcha, onShowChange]);

  async function handleToggle(checked: boolean | "indeterminate") {
    if (!checked) {
      setState("idle");
      setChecked(false);
      onValidChange?.(false);
      return;
    }
    setState("verifying");
    const result = await solveCaptcha();
    if (result.status === "ok") {
      setState("verified");
      setChecked(true);
      onValidChange?.(true);
    } else {
      setState("idle");
      setChecked(false);
      onValidChange?.(false);
    }
  }

  if (!show) {
    return (
      <div aria-hidden="true" className="hidden">
        <input
          name="website"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          className="absolute -left-[9999px] h-0 w-0"
        />
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="relative flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-card">
          <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
          <span
            aria-hidden="true"
            className={cn(
              "pointer-events-none absolute inset-0 rounded-full opacity-30 transition-transform",
              "bg-[radial-gradient(circle_at_30%_25%,rgba(255,255,255,0.9),transparent_45%)]",
            )}
          />
        </div>
        <label className="flex flex-1 cursor-pointer items-center gap-3">
          <Checkbox
            checked={checked}
            onCheckedChange={handleToggle}
            disabled={state === "verifying"}
            aria-label="I'm not a robot"
          />
          <span className="text-sm font-medium">I&apos;m not a robot</span>
          {state === "verifying" && (
            <LoaderCircle
              aria-hidden="true"
              className="ml-auto size-4 animate-spin text-muted-foreground"
            />
          )}
          {state === "verified" && (
            <Sparkles
              aria-hidden="true"
              className="ml-auto size-4 text-primary"
            />
          )}
        </label>
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-border/70 pt-2">
        <p className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          <Sparkles aria-hidden="true" className="size-3" />
          Skyrict Shield
        </p>
        <p className="font-mono text-[10px] text-muted-foreground">
          {state === "verified" ? (
            "Verified"
          ) : (
            <>
              Privacy
              Terms
            </>
          )}
        </p>
      </div>
      <input
        aria-hidden="true"
        name="website"
        tabIndex={-1}
        autoComplete="off"
        className="absolute -left-[9999px] h-0 w-0"
      />
    </div>
  );
}

export { RiskChallenge };
