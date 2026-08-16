import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";

export interface BreakdownSegment {
  label: string;
  value: number;
  /** Literal Tailwind background class for the bar and legend dot. */
  colorClass: string;
  /** When set, the legend row links through to the filtered view. */
  href?: string;
}

interface StatusBreakdownProps {
  title: string;
  segments: BreakdownSegment[];
  total: number;
}

/** A stacked-bar summary of related quantities, each segment linkable. */
export function StatusBreakdown({ title, segments, total }: StatusBreakdownProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      {total > 0 ? (
        <>
          <div
            className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-muted"
            role="img"
            aria-label={title}
          >
            {segments.map((segment) => (
              <div
                key={segment.label}
                className={cn(segment.colorClass, segment.value === 0 && "hidden")}
                style={{ width: `${(segment.value / total) * 100}%` }}
              />
            ))}
          </div>
          <ul className="mt-4 space-y-2">
            {segments.map((segment) => (
              <li key={segment.label}>
                {segment.href ? (
                  <Link
                    href={segment.href}
                    className="group flex items-center gap-2 rounded-md text-sm transition-colors hover:text-foreground"
                  >
                    <span
                      className={cn("size-2.5 shrink-0 rounded-sm", segment.colorClass)}
                      aria-hidden="true"
                    />
                    <span className="text-muted-foreground group-hover:text-foreground">
                      {segment.label}
                    </span>
                    <span className="ml-auto font-medium text-foreground">{segment.value}</span>
                    <ArrowRight
                      aria-hidden="true"
                      className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                    />
                  </Link>
                ) : (
                  <span className="flex items-center gap-2 text-sm">
                    <span
                      className={cn("size-2.5 shrink-0 rounded-sm", segment.colorClass)}
                      aria-hidden="true"
                    />
                    <span className="text-muted-foreground">{segment.label}</span>
                    <span className="ml-auto font-medium text-foreground">{segment.value}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">No records yet.</p>
      )}
    </div>
  );
}
