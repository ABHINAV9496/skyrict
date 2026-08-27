"use client"

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

interface TruncatedTooltipProps {
  text: string;
  className?: string;
}

function useIsTruncated(ref: React.RefObject<HTMLElement | null>) {
  const [truncated, setTruncated] = useState(false);

  const check = useCallback(() => {
    const el = ref.current;
    if (el) {
      setTruncated(el.scrollWidth > el.clientWidth);
    }
  }, [ref]);

  useLayoutEffect(() => {
    check();
  }, [check]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new ResizeObserver(check);
    observer.observe(el);

    window.addEventListener("resize", check);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", check);
    };
  }, [check, ref]);

  return truncated;
}

function TruncatedTooltip({
  text,
  className,
}: TruncatedTooltipProps) {
  const spanRef = useRef<HTMLSpanElement>(null);
  const truncated = useIsTruncated(spanRef);

  if (!text) {
    return <span className={cn("text-sm text-muted-foreground", className)}>{"\u2014"}</span>;
  }

  const span = (
    <span ref={spanRef} className={cn("block truncate text-sm", className)}>
      {text}
    </span>
  );

  if (!truncated) {
    return span;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span ref={spanRef} className={cn("block truncate text-sm", className)}>
          {text}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6}>
        {text}
      </TooltipContent>
    </Tooltip>
  );
}

export { TruncatedTooltip }
export type { TruncatedTooltipProps }
