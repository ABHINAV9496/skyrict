"use client";

import type { ReactNode } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ToolbarTab {
  key: string;
  label: string;
  count?: number;
}

interface TableToolbarProps {
  searchPlaceholder?: string;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  tabs?: ToolbarTab[];
  activeTab?: string;
  onTabChange?: (key: string) => void;
  period?: ReactNode;
  actions?: ReactNode;
  left?: ReactNode;
}

function TableToolbar({
  searchPlaceholder,
  searchValue,
  onSearchChange,
  tabs,
  activeTab,
  onTabChange,
  period,
  actions,
  left,
}: TableToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
        {left ? <div className="flex items-center gap-3">{left}</div> : null}
        {onSearchChange ? (
          <div className="relative w-56">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder={searchPlaceholder ?? "Search…"}
              className="pl-7"
            />
          </div>
        ) : null}
        {tabs ? (
          <div
            role="group"
            aria-label="Filter"
            className="inline-flex rounded-lg border border-border bg-card p-0.5"
          >
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                aria-pressed={activeTab === tab.key}
                onClick={() => onTabChange?.(tab.key)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  activeTab === tab.key
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
                {typeof tab.count === "number" ? (
                  <span className={cn("ml-1.5 text-xs", activeTab === tab.key ? "text-primary-foreground/80" : "text-muted-foreground/70")}>
                    {tab.count}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {period}
        {actions}
      </div>
    </div>
  );
}

export { TableToolbar };
