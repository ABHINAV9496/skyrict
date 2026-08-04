"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { AuthInput, type AuthInputProps } from "@/lib/auth/AuthInput";

type PasswordFieldProps = Omit<AuthInputProps, "type" | "trailing">;

function PasswordField({ id, ...props }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <AuthInput
      id={id}
      type={visible ? "text" : "password"}
      trailing={
        <button
          type="button"
          onClick={() => setVisible((value) => !value)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          className="flex h-10 w-10 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
        >
          {visible ? (
            <EyeOff aria-hidden="true" className="size-4" />
          ) : (
            <Eye aria-hidden="true" className="size-4" />
          )}
        </button>
      }
      {...props}
    />
  );
}

export { PasswordField };
