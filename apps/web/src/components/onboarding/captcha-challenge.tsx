"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getCaptcha } from "@/lib/api/auth-api";
import { AuthInput } from "@/lib/auth/AuthInput";

export interface CaptchaValue {
  captchaId: string;
  answer: string;
}

function CaptchaChallenge({
  onCaptchaChange,
  onError,
  revision = 0,
}: {
  onCaptchaChange?: (value: CaptchaValue | null) => void;
  onError?: (failed: boolean) => void;
  revision?: number;
}) {
  const [captchaId, setCaptchaId] = useState("");
  const [image, setImage] = useState("");
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(true);

  const loadCaptcha = useCallback(async () => {
    setLoading(true);
    setValue("");
    onCaptchaChange?.(null);
    try {
      const captcha = await getCaptcha();
      setCaptchaId(captcha.captchaId);
      setImage(captcha.image);
      setLoading(false);
      onError?.(false);
    } catch {
      setLoading(false);
      onError?.(true);
    }
  }, [onCaptchaChange, onError]);

  useEffect(() => {
    loadCaptcha();
    // Only refresh when the parent explicitly bumps `revision` (e.g. after a
    // failed submit). Parent re-renders while typing must not reset the image.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision]);

  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const next = event.target.value;
    setValue(next);
    const trimmed = next.trim();
    if (trimmed && captchaId) {
      onCaptchaChange?.({ captchaId, answer: trimmed });
    } else {
      onCaptchaChange?.(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 p-3 shadow-sm">
        <div className="relative flex min-h-14 flex-1 select-none items-center justify-center overflow-hidden rounded-md border border-border/70 bg-card">
          {loading ? (
            <Loader2
              aria-hidden="true"
              className="size-5 animate-spin text-muted-foreground"
            />
          ) : image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={image}
              alt="Security code image"
              className="h-14 w-full object-contain"
            />
          ) : null}
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="shrink-0 text-muted-foreground hover:text-foreground"
          onClick={loadCaptcha}
          disabled={loading}
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
      />
    </div>
  );
}

export { CaptchaChallenge };
