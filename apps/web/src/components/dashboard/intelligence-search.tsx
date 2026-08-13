"use client";

import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LoaderCircle, Search } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The Intelligence world's search input. The compact variant lives in the
 * navbar and shows the current query; the hero variant is the landing page's
 * main attraction.
 */
export function IntelligenceSearch({
  variant = "navbar",
}: {
  variant?: "navbar" | "hero";
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [pending, setPending] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    if (!value || pending) return;
    setPending(true);
    router.push(`/dashboard/intelligence/results?q=${encodeURIComponent(value)}`);
  };

  const hero = variant === "hero";

  return (
    <form
      onSubmit={submit}
      role="search"
      className={cn(
        "relative w-full",
        hero ? "max-w-2xl" : "max-w-xl",
      )}
    >
      <Search
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground",
          hero ? "size-5" : "size-4",
        )}
      />
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search the market — competitors, trends, niches…"
        aria-label="Search the market"
        className={cn(
          "w-full rounded-full border border-border bg-card text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          hero
            ? "py-4 pl-12 pr-12 text-base shadow-lg shadow-primary/5"
            : "py-2.5 pl-10 pr-10 text-sm",
        )}
      />
      {pending ? (
        <LoaderCircle
          aria-hidden="true"
          className={cn(
            "absolute right-3.5 top-1/2 -translate-y-1/2 animate-spin text-primary",
            hero ? "size-5" : "size-4",
          )}
        />
      ) : null}
    </form>
  );
}
