"use client";

import { Lock } from "lucide-react";

import { cn } from "@/lib/utils";

type TrustIndicatorProps = {
  label?: string;
  className?: string;
};

function TrustIndicator({
  label = "Encrypted & secure sign-in",
  className,
}: TrustIndicatorProps) {
  return (
    <p
      className={cn(
        "flex items-center justify-center gap-1.5 text-center text-sm text-muted-foreground",
        className,
      )}
    >
      <Lock aria-hidden="true" className="size-3.5" />
      {label}
    </p>
  );
}

export { TrustIndicator };
