"use client";

import {
  passwordStrength,
  strengthColors,
  strengthLabels,
} from "@/lib/auth/password";
import { cn } from "@/lib/utils";

function PasswordStrength({ password }: { password: string }) {
  if (!password) return null;

  const rawScore = passwordStrength(password);
  const score = Math.min(rawScore, strengthLabels.length - 1);

  return (
    <div className="space-y-1" aria-live="polite">
      <div className="flex gap-1" aria-hidden="true">
        {Array.from({ length: 4 }, (_, i) => (
          <span
            key={i}
            className={cn(
              "h-1 w-full rounded-full transition-colors",
              i < score ? strengthColors[score] : "bg-border",
            )}
          />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Password strength:{" "}
        <span className="font-medium text-foreground">
          {strengthLabels[score]}
        </span>
      </p>
    </div>
  );
}

export { PasswordStrength };
