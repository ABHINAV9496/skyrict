"use client";

import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";

type AuthButtonProps = React.ComponentProps<typeof Button> & {
  loading?: boolean;
};

function AuthButton({
  loading = false,
  children,
  disabled,
  ...props
}: AuthButtonProps) {
  return (
    <Button disabled={disabled || loading} {...props}>
      {loading ? (
        <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
      ) : null}
      {children}
    </Button>
  );
}

export { AuthButton };
