import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/dashboard/shared/status-badge";

export interface ActivityItem {
  key: string;
  icon?: ReactNode;
  title: string;
  meta?: string;
  status?: string;
  time?: string;
  href?: string;
}

interface RecentActivityListProps {
  title: string;
  items: ActivityItem[];
  emptyMessage: string;
}

/** A compact feed of recent records, each with an optional detail link. */
export function RecentActivityList({ title, items, emptyMessage }: RecentActivityListProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <ul className="mt-3 divide-y divide-border/60">
          {items.map((item) => (
            <li key={item.key} className="flex items-center gap-3 py-2.5 first:pt-1 last:pb-0">
              {item.icon ? (
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  {item.icon}
                </span>
              ) : null}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
                {item.meta ? <p className="truncate text-xs text-muted-foreground">{item.meta}</p> : null}
              </div>
              {item.status ? <StatusBadge status={item.status} /> : null}
              {item.time ? <span className="shrink-0 text-xs text-muted-foreground">{item.time}</span> : null}
              {item.href ? (
                <Link
                  href={item.href}
                  className="group inline-flex shrink-0 items-center gap-1 text-sm font-medium text-primary"
                >
                  View
                  <ArrowRight
                    aria-hidden="true"
                    className="size-3.5 transition-transform group-hover:translate-x-0.5"
                  />
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
