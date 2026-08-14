"use client";

import type { FC } from "react";
import { Menu, PanelLeft, Share } from "lucide-react";

import { useAgentsUI } from "@/components/dashboard/agents/agents-shell";
import { Button } from "@/components/ui/button";

/**
 * Shared chat chrome for the AI Agents world: menu (mobile), sidebar collapse
 * toggle (desktop), the thread title, and a trailing action slot.
 */
export const AgentsHeader: FC<{ title?: string }> = ({ title }) => {
  const { collapsed, toggleCollapsed, openMobile } = useAgentsUI();

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 px-4">
      <Button
        variant="ghost"
        size="icon"
        className="size-8 shrink-0 md:hidden"
        onClick={openMobile}
        aria-label="Toggle menu"
      >
        <Menu className="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="hidden size-8 md:flex"
        onClick={toggleCollapsed}
        title={collapsed ? "Show sidebar" : "Hide sidebar"}
        aria-label={collapsed ? "Show sidebar" : "Hide sidebar"}
      >
        <PanelLeft className="size-4" />
      </Button>
      <span className="min-w-0 truncate text-sm font-medium text-foreground">
        {title ?? "New Chat"}
      </span>
      <Button
        variant="ghost"
        size="icon"
        className="ml-auto size-8"
        title="Share"
        aria-label="Share"
        disabled
      >
        <Share className="size-4" />
      </Button>
    </header>
  );
};
