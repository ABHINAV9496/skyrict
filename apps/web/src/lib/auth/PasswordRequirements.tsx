"use client";

import { CheckCircle2, Circle } from "lucide-react";

import { passwordRequirements } from "@/lib/auth/password";

function PasswordRequirements({ password }: { password: string }) {
  if (!password) return null;

  return (
    <ul className="grid gap-1.5 pt-1 sm:grid-cols-2" aria-live="polite">
      {passwordRequirements.map((requirement) => {
        const met = requirement.test(password);
        return (
          <li key={requirement.label} className="flex items-center gap-2 text-xs">
            {met ? (
              <CheckCircle2
                aria-hidden="true"
                className="size-3.5 shrink-0 text-primary"
              />
            ) : (
              <Circle
                aria-hidden="true"
                className="size-3.5 shrink-0 text-muted-foreground/60"
              />
            )}
            <span
              className={
                met ? "text-foreground" : "text-muted-foreground"
              }
            >
              {requirement.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export { PasswordRequirements };
