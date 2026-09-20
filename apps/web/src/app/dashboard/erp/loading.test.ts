import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import ErpLoading from "@/app/dashboard/erp/loading";

/**
 * Regression guard for the ERP entry flash.
 *
 * `ShellRouter` mounts `ErpShell` (real sidebar + topbar) around the
 * `/dashboard/erp` segment, and a segment `loading.tsx` renders *inside* that
 * shell. The fallback therefore must stand in for the page body only - a
 * second `<aside>`/`<nav>`/`h-dvh` world here stacks a skeleton sidebar and
 * topbar on top of the live chrome and reads as a bug.
 */
function renderFallback() {
    return renderToStaticMarkup(createElement(ErpLoading));
}

describe("ErpLoading", () => {
    it("paints no module chrome of its own", () => {
        const html = renderFallback();
        expect(html).not.toContain("<aside");
        expect(html).not.toContain("<nav");
    });

    it("does not claim the viewport like a full world skeleton", () => {
        expect(renderFallback()).not.toContain("h-dvh");
    });

    it("stands in for the content with the shared skeleton primitive", () => {
        expect(renderFallback()).toContain("skeleton");
    });
});
