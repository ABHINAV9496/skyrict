"use client";

import { useLayoutEffect, useState } from "react";

/**
 * Portal container that stays inside the active module theme scope
 * (`data-theme-scope` on the erp/agents/intelligence shells). Returns null
 * when no module theme is present so callers fall back to document.body.
 */
export function useThemeScopeContainer(): HTMLElement | null {
  const [container, setContainer] = useState<HTMLElement | null>(null);

  useLayoutEffect(() => {
    if (typeof document === "undefined") return;
    setContainer(document.querySelector<HTMLElement>("[data-theme-scope]"));
  }, []);

  return container;
}
