"use client";

import { useEffect, useState } from "react";
import { Globe } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { countries } from "@/config/onboarding";

const STORAGE_KEY = "skyrict:gmie:country";

/**
 * Region scoping for market intelligence. Kept local to the GMIE world so the
 * research horizon (competitors, trends, niches) can be set per session without
 * touching workspace data.
 */
export function IntelligenceCountrySelect() {
  const [country, setCountry] = useState<string>("US");

  useEffect(() => {
    setCountry(localStorage.getItem(STORAGE_KEY) ?? "US");
  }, []);

  const change = (value: string) => {
    setCountry(value);
    localStorage.setItem(STORAGE_KEY, value);
  };

  return (
    <Select value={country} onValueChange={change}>
      <SelectTrigger
        size="sm"
        aria-label="Market country"
        title="Market country"
        className="h-9 rounded-full border-border bg-transparent px-3"
      >
        <Globe aria-hidden="true" className="size-4 text-muted-foreground" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end" className="max-h-72">
        {countries.map((entry) => (
          <SelectItem key={entry.code} value={entry.code}>
            {entry.code} · {entry.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
