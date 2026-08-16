"use client";

import { useMemo, useState } from "react";
import { Popover } from "radix-ui";
import { Check, ChevronsUpDown } from "lucide-react";

import { Input } from "@/components/ui/input";
import { useThemeScopeContainer } from "@/lib/theme-scope";
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
  const container = useThemeScopeContainer();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);

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

  function select(account: Account) {
    onChange(account.code);
    setQuery(`${account.code} · ${account.name}`);
    setOpen(false);
  }

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
    if (query.trim()) {
      const exact = accounts.find((account) => account.code === query.trim());
      if (exact) onChange(exact.code);
    }
    setQuery(selected ? `${selected.code} · ${selected.name}` : value);
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <div className="relative">
          <Input
            ref={(el) => {
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
            readOnly={!query}
            onChange={(event) => {
              setQuery(event.target.value);
              setHighlighted(0);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={handleKeyDown}
            onBlur={handleBlur}
            className="pr-7"
          />
          <ChevronsUpDown
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
          />
        </div>
      </Popover.Trigger>
      <Popover.Portal container={container ?? undefined}>
        <Popover.Content
          sideOffset={4}
          align="start"
          className="z-50 w-[var(--radix-popover-trigger-width)] min-w-64 rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md outline-none"
        >
          <div role="listbox" className="max-h-56 overflow-y-auto">
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
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export { AccountCombobox };
