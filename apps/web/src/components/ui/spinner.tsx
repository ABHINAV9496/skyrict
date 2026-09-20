import type { SVGProps } from "react";

import { cn } from "@/lib/utils";

/**
 * Radial segment spinner - the single shared loading indicator for the app.
 *
 * Eight short rounded bars arranged around a circle, with a soft trailing
 * transparency fade, rotating continuously.
 *
 * Color: the bars draw in the theme's muted terminal gray
 * (`text-muted-foreground`) by default in every theme, so standalone and
 * inline spinners read as the soft white/gray tone of the product. An
 * explicit color class passed via `className` (for example `text-primary`)
 * overrides it, which keeps spinner color in line with its surrounding
 * text/button.
 *
 * Speed: one full rotation every 0.7s - snappier than the old 1s
 * `animate-spin` default, without being frantic.
 *
 * It is a drop-in visual replacement for the former per-site lucide spin
 * icons (`LoaderCircle`/`Loader2`/`RefreshCw` + `animate-spin`) and the old
 * CSS border spinner: pass the same `size-*`/margin/positioning classes that
 * were on the icon.  The rendered box is identical at every size, so layouts
 * do not shift.
 *
 * Note: the `spin` animation is applied here (with its own duration) - call
 * sites must not also pass `animate-spin`.
 */

const SEGMENTS = 8;
/** Leading bar opacity -> last bar opacity (soft comet-trail fade). */
const FADE_MIN = 0.15;
/** Seconds per full rotation. */
const ROTATION_SECONDS = 0.7;

export function Spinner({ className, ...props }: SVGProps<SVGSVGElement>) {
    return (
        <svg
            viewBox="0 0 24 24"
            width={24}
            height={24}
            fill="none"
            aria-hidden="true"
            className={cn("animate-spin text-muted-foreground", className)}
            style={{ animationDuration: `${ROTATION_SECONDS}s` }}
            {...props}
        >
            {Array.from({ length: SEGMENTS }, (_, i) => {
                const opacity = Number(
                    (1 - ((1 - FADE_MIN) * i) / (SEGMENTS - 1)).toFixed(3),
                );
                return (
                    <rect
                        key={i}
                        x={10.75}
                        y={2.25}
                        width={2.5}
                        height={6}
                        rx={1.25}
                        fill="currentColor"
                        opacity={opacity}
                        transform={`rotate(${i * (360 / SEGMENTS)} 12 12)`}
                    />
                );
            })}
        </svg>
    );
}