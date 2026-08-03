"use client";

import { useState } from "react";
import { CheckCircle2, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { AuthInput } from "@/lib/auth/AuthInput";

const CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function generateCaptchaCode(length = 5): string {
  const values = new Uint32Array(length);
  crypto.getRandomValues(values);
  return Array.from(
    values,
    (n) => CAPTCHA_ALPHABET[n % CAPTCHA_ALPHABET.length],
  ).join("");
}

function normalize(value: string): string {
  return value.trim().toUpperCase();
}

function CaptchaChallenge({
  onValidChange,
}: {
  onValidChange?: (valid: boolean) => void;
}) {
  const [code, setCode] = useState(() => generateCaptchaCode());
  const [value, setValue] = useState("");
  const [valid, setValid] = useState(false);

  function regenerate() {
    const next = generateCaptchaCode();
    setCode(next);
    setValue("");
    setValid(false);
    onValidChange?.(false);
  }

  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const next = event.target.value;
    setValue(next);
    const isMatch = normalize(next) === code;
    setValid(isMatch);
    onValidChange?.(isMatch);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 p-3 shadow-sm">
        <div
          aria-label={`Captcha code: ${code}`}
          className="relative flex min-h-11 flex-1 select-none items-center justify-center overflow-hidden rounded-md border border-border/70 bg-card px-3 py-2"
        >
          <span className="relative flex items-center gap-1.5 font-mono text-xl font-semibold tracking-[0.25em] text-foreground/90">
            {code.split("").map((ch, index) => (
              <span
                key={index}
                aria-hidden="true"
                className="inline-block"
                style={{
                  transform: `rotate(${(index % 2 === 0 ? -1 : 1) * 8}deg) translateY(${
                    index % 3 === 0 ? -2 : 1
                  }px)`,
                }}
              >
                {ch}
              </span>
            ))}
          </span>
          <span
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 right-0 left-0 h-px bg-foreground/15"
            style={{ transform: "rotate(-4deg)" }}
          />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute top-1/3 right-0 left-0 h-px bg-foreground/10"
            style={{ transform: "rotate(3deg)" }}
          />
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="shrink-0 text-muted-foreground hover:text-foreground"
          onClick={regenerate}
          aria-label="Get a new code"
        >
          <RotateCw aria-hidden="true" className="size-4" />
        </Button>
      </div>

      <AuthInput
        id="captcha-input"
        label="Enter the code"
        value={value}
        onChange={handleChange}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        placeholder="Type the code above"
        hint="Characters are not case-sensitive."
        trailing={
          valid ? (
            <CheckCircle2
              aria-hidden="true"
              className="mr-1 size-4 text-primary"
            />
          ) : null
        }
      />
    </div>
  );
}

export { CaptchaChallenge };
