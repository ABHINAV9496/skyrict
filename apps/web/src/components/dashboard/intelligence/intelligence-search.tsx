"use client";

import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LoaderCircle, Search } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The Intelligence world's search input. The hero variant is the landing
 * page's main attraction; the inline variant is the compact input used inside
 * pages (results, explore).
 */
export function IntelligenceSearch({
  variant = "inline",
}: {
  variant?: "hero" | "inline";
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
            ? "py-4 pl-12 pr-32 text-base shadow-lg shadow-primary/5"
            : "py-2.5 pl-10 pr-10 text-sm",
        )}
      />
      {hero ? (
        <button
          type="submit"
          disabled={pending || !query.trim()}
          aria-label="Search"
          className={cn(
            "absolute inset-y-2 right-2 flex items-center gap-1.5 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors",
            pending || !query.trim()
              ? "cursor-not-allowed opacity-60"
              : "hover:bg-primary/90",
          )}
        >
          {pending ? (
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
          ) : (
            <Search aria-hidden="true" className="size-4" />
          )}
          Search
        </button>
      ) : pending ? (
        <LoaderCircle
          aria-hidden="true"
          className="absolute right-3.5 top-1/2 size-4 -translate-y-1/2 animate-spin text-primary"
        />
      ) : null}
    </form>
  );
}
