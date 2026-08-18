"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ContactRound,
  LoaderCircle,
  Search,
  SearchX,
  TrendingUp,
  UserPlus,
  Users,
} from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { searchCrm, type CrmEntityType, type SearchHit } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { ENTITY_TYPE_LABELS } from "@/lib/erp/labels";
import { cn } from "@/lib/utils";

type SearchStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; hits: SearchHit[]; total: number; searchedQuery: string };

type SearchType = CrmEntityType | "all";

const TYPE_OPTIONS: { value: SearchType; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "lead", label: "Leads" },
  { value: "opportunity", label: "Opportunities" },
  { value: "customer", label: "Customers" },
  { value: "contact", label: "Contacts" },
];

function hitDestination(hit: SearchHit): string {
  switch (hit.entityType) {
    case "lead":
      return `/dashboard/erp/crm/leads/${hit.entityId}`;
    case "opportunity":
      return `/dashboard/erp/crm/opportunities/${hit.entityId}`;
    case "customer":
      return `/dashboard/erp/crm/customers/${hit.entityId}`;
    case "contact":
      return "/dashboard/erp/crm/contacts";
  }
}

function HitIcon({ entityType }: { entityType: CrmEntityType }) {
  switch (entityType) {
    case "lead":
      return <UserPlus aria-hidden="true" className="size-4" />;
    case "opportunity":
      return <TrendingUp aria-hidden="true" className="size-4" />;
    case "customer":
      return <Users aria-hidden="true" className="size-4" />;
    case "contact":
      return <ContactRound aria-hidden="true" className="size-4" />;
  }
}

export function CrmSearch() {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<SearchType>("all");
  const [status, setStatus] = useState<SearchStatus>({ state: "idle" });
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const run = useCallback(
    async (term: string, entityType: SearchType) => {
      const trimmed = term.trim();
      if (!trimmed) {
        setStatus({ state: "idle" });
        return;
      }
      setStatus({ state: "loading" });
      try {
        const result = await searchCrm(trimmed, {
          type: entityType === "all" ? undefined : entityType,
          limit: 50,
        });
        setStatus({
          state: "ready",
          hits: result.data,
          total: result.meta?.total ?? result.data.length,
          searchedQuery: trimmed,
        });
      } catch (error) {
        setStatus({
          state: "error",
          message: error instanceof ApiError ? error.message : "Search failed.",
        });
      }
    },
    [],
  );

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void run(query, type);
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, type, run]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search leads, opportunities, customers, and contacts…"
            className="pl-9"
            aria-label="Search CRM records"
            autoFocus
          />
        </div>
        <Select value={type} onValueChange={(value) => setType(value as SearchType)}>
          <SelectTrigger className="sm:w-48" aria-label="Filter by record type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TYPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {status.state === "idle" ? (
        <EmptyState
          icon={Search}
          title="Search the CRM"
          description="Type at least one character to search leads, opportunities, customers, and contacts across your workspace."
        />
      ) : null}

      {status.state === "loading" ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <LoaderCircle aria-hidden="true" className="size-5 animate-spin" />
        </div>
      ) : null}

      {status.state === "error" ? (
        <ErrorState
          message={status.message}
          onRetry={() => void run(query, type)}
        />
      ) : null}

      {status.state === "ready" ? (
        status.hits.length === 0 ? (
          <EmptyState
            icon={SearchX}
            title={`No results for “${status.searchedQuery}”`}
            description="Try a different spelling, a broader term, or switch the record type filter."
          />
        ) : (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {status.total} result{status.total === 1 ? "" : "s"} for{" "}
              <span className="font-medium text-foreground">“{status.searchedQuery}”</span>
            </p>
            <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border bg-card">
              {status.hits.map((hit) => (
                <li key={`${hit.entityType}-${hit.entityId}`}>
                  <Link
                    href={hitDestination(hit)}
                    className={cn(
                      "flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50",
                    )}
                  >
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <HitIcon entityType={hit.entityType} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-foreground">
                        {hit.title || "Unnamed record"}
                      </span>
                      {hit.subtitle ? (
                        <span className="block truncate text-xs text-muted-foreground">
                          {hit.subtitle}
                        </span>
                      ) : null}
                    </span>
                    <Badge
                      variant="outline"
                      className="shrink-0 bg-muted text-muted-foreground ring-1 ring-border"
                    >
                      {ENTITY_TYPE_LABELS[hit.entityType]}
                    </Badge>
                    <ArrowRight
                      aria-hidden="true"
                      className="size-4 shrink-0 text-muted-foreground/60"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )
      ) : null}
    </div>
  );
}
