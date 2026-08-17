"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronsUpDown } from "lucide-react";

import { Input } from "@/components/ui/input";
import type { Account } from "@/lib/api/finance-api";
import { cn } from "@/lib/utils";

interface AccountComboboxProps {
  accounts: Account[];
  value: string;
  onChange: (code: string) => void;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  invalid?: boolean;
  autoFocus?: boolean;
  inputRef?: (el: HTMLInputElement | null) => void;
}

function AccountCombobox({
  accounts,
  value,
  onChange,
  placeholder,
  id,
  disabled,
  invalid,
  autoFocus,
  inputRef,
}: AccountComboboxProps) {
  const triggerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputElRef = useRef<HTMLInputElement | null>(null);
  const justSelectedRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number }>({
    top: 0,
    left: 0,
    width: 0,
  });

  const selected = useMemo(
    () => accounts.find((account) => account.code === value) ?? null,
    [accounts, value],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return accounts;
    return accounts.filter(
      (account) =>
        account.code.toLowerCase().includes(needle) ||
        account.name.toLowerCase().includes(needle),
    );
  }, [accounts, query]);

  useEffect(() => {
    setHighlighted(0);
  }, [filtered.length, query]);

  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    if (!list) return;
    const item = list.children[highlighted] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [highlighted, open]);

  const updatePosition = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setDropdownPos({
      top: rect.bottom + 4,
      left: rect.left,
      width: rect.width,
    });
  }, []);

  const select = useCallback(
    (account: Account) => {
      justSelectedRef.current = true;
      onChange(account.code);
      setQuery(`${account.code} \u00b7 ${account.name}`);
      setOpen(false);
    },
    [onChange],
  );

  useEffect(() => {
    if (!open) return;
    updatePosition();
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        listRef.current && !listRef.current.contains(target)
      ) {
        setOpen(false);
      }
    }
    function handleScroll() {
      updatePosition();
    }
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", updatePosition);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", updatePosition);
    };
  }, [open, updatePosition]);

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setHighlighted((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const match =
        filtered[highlighted] ?? filtered.find((account) => account.code === query.trim());
      if (match) select(match);
      else setOpen(false);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  function handleBlur() {
    setTimeout(() => {
      if (justSelectedRef.current) {
        justSelectedRef.current = false;
        return;
      }
      if (query.trim()) {
        const exact = accounts.find((account) => account.code === query.trim());
        if (exact) onChange(exact.code);
      }
      setQuery(selected ? `${selected.code} \u00b7 ${selected.name}` : value);
    }, 150);
  }

  return (
    <>
      <div ref={triggerRef} className="relative">
        <Input
          ref={(el) => {
            inputElRef.current = el;
            if (inputRef) inputRef(el);
          }}
          id={id}
          value={query}
          autoFocus={autoFocus}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          aria-haspopup="listbox"
          aria-expanded={open}
          placeholder={placeholder ?? "Select account"}
          onChange={(event) => {
            setQuery(event.target.value);
            setHighlighted(0);
            setOpen(true);
          }}
          onFocus={() => {
            updatePosition();
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          className="pr-7"
        />
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2"
          onMouseDown={(event) => {
            event.preventDefault();
            setOpen((prev) => !prev);
          }}
        >
          <ChevronsUpDown className="size-3.5 text-muted-foreground" />
        </button>
      </div>
      {open
        ? createPortal(
            <div
              ref={listRef}
              role="listbox"
              style={{
                position: "fixed",
                top: dropdownPos.top,
                left: dropdownPos.left,
                width: dropdownPos.width,
                zIndex: 9999,
              }}
              className="max-h-56 min-w-64 overflow-y-auto rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md outline-none"
            >
              {filtered.length === 0 ? (
                <p className="px-2 py-3 text-center text-sm text-muted-foreground">
                  No matching accounts
                </p>
              ) : (
                filtered.map((account, index) => (
                  <button
                    key={account.id}
                    type="button"
                    role="option"
                    aria-selected={account.code === value}
                    onMouseEnter={() => setHighlighted(index)}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      select(account);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                      index === highlighted ? "bg-muted" : "hover:bg-muted",
                    )}
                  >
                    <span className="min-w-0 truncate">
                      <code className="mr-2 font-mono text-xs">{account.code}</code>
                      {account.name}
                    </span>
                    {account.code === value ? (
                      <Check aria-hidden="true" className="size-3.5 shrink-0 text-primary" />
                    ) : null}
                  </button>
                ))
              )}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

export { AccountCombobox };
