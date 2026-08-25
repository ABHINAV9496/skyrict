"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type SearchableSelectOption = {
  /** Value emitted by onValueChange (an id, code, or enum value). */
  value: string;
  /** Main row text — also the committed/resting input label. */
  label: string;
  /** Optional secondary text shown at the row end. */
  hint?: string;
  /** Extra haystack text matched while searching but never displayed. */
  keywords?: string;
};

/**
 * Generic searchable dropdown replacing native `<Select>` pickers whose
 * option lists outgrow a few entries (employees, leave types, departments).
 * Mirrors the battle-tested CountryCombobox interaction: the listbox renders
 * inline under the input (staying inside Radix's scroll-lock scope), typing
 * filters case-insensitively with prefix matches ranked first, and the
 * committed value is always an option id — the visible text is just its
 * resting label, reset on blur.
 *
 * Escape handling mirrors CountryCombobox: a document-capture listener
 * swallows Escape while it targets this combobox so closing the listbox can
 * never dismiss the surrounding Radix dialog.
 */
export function SearchableSelect({
  options,
  value,
  onValueChange,
  id,
  disabled,
  invalid,
  placeholder,
  emptyMessage = "No matches",
  className,
}: {
  options: SearchableSelectOption[];
  value: string | null;
  onValueChange: (value: string) => void;
  id?: string;
  disabled?: boolean;
  invalid?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const justSelectedRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);

  const selected = useMemo(
    () =>
      value != null && value !== ""
        ? options.find((option) => option.value === value) ?? null
        : null,
    [options, value],
  );

  // Keep the visible label in sync whenever the selection changes externally
  // (dialog reset on open, edit-mode init, prefilled employee filters).
  useEffect(() => {
    setQuery(selected ? selected.label : "");
  }, [selected]);

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
    if (!needle || needle === (selected?.label.toLowerCase() ?? "")) return options;
    const prefix: SearchableSelectOption[] = [];
    const infix: SearchableSelectOption[] = [];
    for (const option of options) {
      const haystack =
        `${option.label} ${option.keywords ?? ""}`.toLowerCase();
      if (option.label.toLowerCase().startsWith(needle)) {
        prefix.push(option);
      } else if (haystack.includes(needle)) {
        infix.push(option);
      }
    }
    return prefix.concat(infix);
  }, [options, query, selected]);

  function scrollOptionIntoView(index: number, smooth = false) {
    const item = listRef.current?.children[index] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
  }

  // New filter output: restart at the top row and reveal it.
  useEffect(() => {
    setHighlighted(0);
    requestAnimationFrame(() => scrollOptionIntoView(0));
  }, [filtered.length, query]);

  // Opening reveals the currently selected entry instead of always row 0.
  useEffect(() => {
    if (!open) return;
    const index = options.findIndex((option) => option.value === value);
    const start = index >= 0 ? index : 0;
    setHighlighted(start);
    requestAnimationFrame(() => scrollOptionIntoView(start));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const openListbox = useCallback(() => {
    justSelectedRef.current = false;
    setOpen(true);
    requestAnimationFrame(() => inputRef.current?.select());
  }, []);

  const select = useCallback(
    (option: SearchableSelectOption) => {
      justSelectedRef.current = true;
      setQuery(option.label);
      onValueChange(option.value);
      setOpen(false);
      requestAnimationFrame(() => inputRef.current?.select());
    },
    [onValueChange],
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
      setQuery(selected ? selected.label : "");
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
        placeholder={placeholder}
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
        className={className}
      />
      {open ? (
        <div
          ref={listRef}
          role="listbox"
          className="absolute top-full left-0 z-50 mt-1 max-h-56 w-full min-w-48 overflow-y-auto rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md outline-none"
        >
          {filtered.length === 0 ? (
            <p className="px-2 py-3 text-center text-sm text-muted-foreground">
              {emptyMessage}
            </p>
          ) : (
            filtered.map((option, index) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
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
                <span className="min-w-0 truncate">{option.label}</span>
                {option.hint ? (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {option.hint}
                  </span>
                ) : null}
                {option.value === value ? (
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
