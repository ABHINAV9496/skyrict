"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check } from "lucide-react";

import { Input } from "@/components/ui/input";
import { COUNTRIES } from "@/lib/hr/countries";
import { CURRENCIES } from "@/lib/hr/currencies";
import { cn } from "@/lib/utils";

type Option = {
  /** Value emitted by onChange: an ISO country code or a currency code. */
  id: string;
  /** Monospace badge shown at the start of the row ("+91" / "INR"). */
  badge: string;
  /** Main row text after the badge (country name; empty for currencies). */
  primary: string;
  /**
   * Text shown in the input while resting (committed / blurred): dial code
   * only for countries ("+91"), the code for currencies ("INR").
   */
  restingLabel: string;
  /** Lowercase haystack used for filtering. */
  haystack: string;
  /** Lowercase names whose prefix promotes this option above infix matches. */
  names: string[];
};

/**
 * Searchable picker shared by the hire dialog's Phone-country and Currency
 * fields. The two fields are fully independent: the phone field emits country
 * codes and the currency field emits currency codes, and neither selection
 * rewrites the other.
 *
 * The listbox is rendered inline (absolutely positioned under the input)
 * rather than through a portal: staying inside the DialogContent subtree
 * keeps it inside Radix's scroll-lock scope, so mouse-wheel scrolling works,
 * outside-click/focus dismissal never sees it, and it inherits the dialog's
 * theme tokens without any container lookup.
 */
export function CountryCombobox({
  kind,
  value,
  onChange,
  id,
  disabled,
  invalid,
  placeholder,
  className,
}: {
  kind: "country" | "currency";
  value: string | null;
  onChange: (id: string) => void;
  id?: string;
  disabled?: boolean;
  invalid?: boolean;
  placeholder?: string;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const justSelectedRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);

  const options = useMemo<Option[]>(() => {
    if (kind === "country") {
      return COUNTRIES.filter((country) => country.dialCode !== null).map(
        (country) => ({
          id: country.code,
          badge: `+${country.dialCode}`,
          primary: country.name,
          restingLabel: `+${country.dialCode}`,
          haystack: `${country.name} ${country.code} +${country.dialCode}`.toLowerCase(),
          names: [country.name.toLowerCase()],
        }),
      );
    }
    return CURRENCIES.map((currency) => ({
      id: currency.code,
      badge: currency.code,
      primary: "",
      restingLabel: currency.code,
      haystack: `${currency.code} ${currency.countries.join(" ")}`.toLowerCase(),
      names: currency.countries.map((name) => name.toLowerCase()),
    }));
  }, [kind]);

  const selected = useMemo(
    () => (value ? options.find((option) => option.id === value) ?? null : null),
    [options, value],
  );

  // Keep the visible label in sync whenever the selection changes externally
  // (form reset on open, edit-mode init).
  useEffect(() => {
    setQuery(selected ? selected.restingLabel : "");
  }, [selected]);

  /**
   * Radix's DismissableLayer listens for Escape on `document` in the capture
   * phase, so a bubble-phase stopPropagation can never shield the dialog.
   * Register an earlier document-capture listener that swallows Escape while
   * it targets this combobox - closing only the listbox, never the dialog.
   */
  useEffect(() => {
    function handleCapture(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      const wrapper = wrapperRef.current;
      if (!wrapper || !event.target) return;
      if (!wrapper.contains(event.target as Node)) return;
      event.stopImmediatePropagation();
      setOpen(false);
    }
    document.addEventListener("keydown", handleCapture, true);
    return () => document.removeEventListener("keydown", handleCapture, true);
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle || needle === (selected?.restingLabel.toLowerCase() ?? "")) return options;
    // Prefix matches rank ahead of substring matches, and within the prefix
    // bucket the shortest matching name wins, so typing "ind" offers India
    // (INR) before Indonesia (IDR) and British Indian Ocean Territory (USD).
    const prefix: Option[] = [];
    const infix: Option[] = [];
    for (const option of options) {
      if (
        option.haystack.startsWith(needle) ||
        option.id.toLowerCase().startsWith(needle) ||
        option.names.some((name) => name.startsWith(needle))
      ) {
        prefix.push(option);
      } else if (option.haystack.includes(needle)) {
        infix.push(option);
      }
    }
    const rank = (option: Option) => {
      if (option.haystack.startsWith(needle)) return 0;
      if (option.id.toLowerCase().startsWith(needle)) return 1;
      return (
        Math.min(
          ...option.names
            .filter((name) => name.startsWith(needle))
            .map((name) => name.length),
        ) + 2
      );
    };
    return prefix.sort((a, b) => rank(a) - rank(b)).concat(infix);
  }, [options, query, selected]);

  function scrollOptionIntoView(index: number, smooth = false) {
    const item = listRef.current?.children[index] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
  }

  // New filter output: restart at the top row and reveal it. Pointer hover
  // deliberately never scrolls - Chrome re-fires mouseenter for rows passing
  // under a stationary cursor while the list scrolls, which would otherwise
  // fight the user's wheel momentum.
  useEffect(() => {
    setHighlighted(0);
    requestAnimationFrame(() => scrollOptionIntoView(0));
  }, [filtered.length, query]);

  // Opening reveals the currently selected entry instead of always row 0.
  useEffect(() => {
    if (!open) return;
    const index = options.findIndex((option) => option.id === value);
    const start = index >= 0 ? index : 0;
    setHighlighted(start);
    requestAnimationFrame(() => scrollOptionIntoView(start));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /**
   * Open the listbox and select the whole input text so the next keystroke
   * replaces the display label instead of appending to it. Also clears a
   * stale just-selected flag so a later blur still closes the list.
   */
  const openListbox = useCallback(() => {
    justSelectedRef.current = false;
    setOpen(true);
    requestAnimationFrame(() => inputRef.current?.select());
  }, []);

  const select = useCallback(
    (option: Option) => {
      justSelectedRef.current = true;
      // Set the label here rather than relying on the selected-sync effect:
      // re-selecting the already-selected value never changes `selected`,
      // so the effect would leave typed search text in the input.
      setQuery(option.restingLabel);
      onChange(option.id);
      setOpen(false);
      // Keep the full label pre-selected so typing right away replaces it.
      requestAnimationFrame(() => inputRef.current?.select());
    },
    [onChange],
  );

  function moveHighlight(delta: number) {
    const next = Math.min(
      Math.max(highlighted + delta, 0),
      Math.max(filtered.length - 1, 0),
    );
    setHighlighted(next);
    scrollOptionIntoView(next, true);
  }

  function commitHighlighted() {
    const match = filtered[highlighted];
    if (match) select(match);
    else setOpen(false);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) openListbox();
      moveHighlight(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openListbox();
        return;
      }
      moveHighlight(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (open) commitHighlighted();
    } else if (event.key === "Escape") {
      // Escape must never reach the Dialog's dismissable layer - with the
      // list already closed it would otherwise close the entire dialog.
      event.stopPropagation();
      if (open) setOpen(false);
    }
  }

  function handleBlur() {
    setTimeout(() => {
      if (justSelectedRef.current) {
        justSelectedRef.current = false;
        return;
      }
      setOpen(false);
      setQuery(selected ? selected.restingLabel : "");
    }, 150);
  }

  return (
    <div ref={wrapperRef} className="relative">
      <Input
        ref={inputRef}
        id={id}
        value={query}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-haspopup="listbox"
        aria-expanded={open}
        autoComplete="off"
        placeholder={
          placeholder ?? (kind === "country" ? "Search country" : "Currency")
        }
        onChange={(event) => {
          setQuery(event.target.value);
          setHighlighted(0);
          setOpen(true);
        }}
        onFocus={() => openListbox()}
        onClick={() => {
          if (!open) openListbox();
        }}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        className={cn("pr-7", className)}
      />
      {open ? (
        <div
          ref={listRef}
          role="listbox"
          className="absolute top-full left-0 z-50 mt-1 max-h-56 w-full min-w-48 overflow-y-auto rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md outline-none"
        >
          {filtered.length === 0 ? (
            <p className="px-2 py-3 text-center text-sm text-muted-foreground">
              No matches
            </p>
          ) : (
            filtered.map((option, index) => (
              <button
                key={option.id}
                type="button"
                role="option"
                aria-selected={option.id === value}
                onMouseEnter={() => setHighlighted(index)}
                onMouseDown={(event) => {
                  event.preventDefault();
                  select(option);
                }}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  index === highlighted ? "bg-muted" : "hover:bg-muted",
                )}
              >
                <span className="min-w-0 truncate">
                  <code className="mr-2 font-mono text-xs">{option.badge}</code>
                  {option.primary}
                </span>
                {option.id === value ? (
                  <Check aria-hidden="true" className="size-3.5 shrink-0 text-primary" />
                ) : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
