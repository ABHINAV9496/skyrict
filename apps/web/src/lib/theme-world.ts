"use client";

/**
 * The nearest module-world wrapper that re-tints the design tokens (theme-erp,
 * theme-agents, ...). Radix primitives portal to document.body by default,
 * which escapes that wrapper's CSS custom-property scope and makes dialogs,
 * selects, and popovers render with the base palette instead of the module's.
 * Mounting them here keeps every floating surface in the same theme as the
 * page behind it. Falls back to document.body when no world wrapper exists
 * (workspace pages, or before the shell mounts) so rendering never throws.
 */
export function getThemeContainer(): HTMLElement | null {
  if (typeof document === "undefined") return null;
  return document.querySelector("[data-theme-world]");
}
