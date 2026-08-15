"use client";

import { cn } from "@/lib/utils";

interface SpotlightOverlayProps {
  active: boolean;
  rect: DOMRect | null;
}

const PADDING = 8;
const OVERLAY_COLOR = "rgb(0 0 0 / 0.45)";

/**
 * Dims the whole viewport except for a rounded "hole" around the highlighted
 * element. The hole is a transparent box whose huge box-shadow creates the
 * dim backdrop; the ring is drawn with a second shadow in the theme ring
 * color. Non-interactive — the tour tooltip handles all interaction.
 */
export function SpotlightOverlay({ active, rect }: SpotlightOverlayProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "fixed inset-0 z-40 transition-opacity duration-200",
        active ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
      )}
    >
      {rect ? (
        <div
          className="absolute transition-all duration-300 ease-out"
          style={{
            top: rect.top - PADDING,
            left: rect.left - PADDING,
            width: rect.width + PADDING * 2,
            height: rect.height + PADDING * 2,
            borderRadius: Math.max(10, rect.height / 2 + PADDING),
            boxShadow: `0 0 0 9999px ${OVERLAY_COLOR}, 0 0 0 1.5px var(--color-primary)`,
          }}
        />
      ) : null}
    </div>
  );
}
