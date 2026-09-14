import { describe, expect, it } from "vitest";

import {
    erpNavGroups,
    isSidebarItemActive,
} from "@/components/dashboard/workspace/sidebar-config";

/* ---------- isSidebarItemActive ---------- */

describe("isSidebarItemActive", () => {
    it("normalises bare paths by prepending /dashboard", () => {
        expect(
            isSidebarItemActive("/erp/documents", {
                href: "/dashboard/erp/documents",
            }),
        ).toBe(true);
    });

    it("matches child paths by prefix when the item is not exact", () => {
        expect(
            isSidebarItemActive("/dashboard/erp/documents/list", {
                href: "/dashboard/erp/documents/list",
            }),
        ).toBe(true);
    });

    it("does not match sibling paths for exact items", () => {
        expect(
            isSidebarItemActive("/dashboard/erp/documents/list", {
                href: "/dashboard/erp/documents",
                exact: true,
            }),
        ).toBe(false);
    });

    it("always matches /dashboard for the workspace root", () => {
        expect(
            isSidebarItemActive("/dashboard", { href: "/dashboard" }),
        ).toBe(true);
    });

    it("normalises / to /dashboard", () => {
        expect(isSidebarItemActive("/", { href: "/dashboard" })).toBe(true);
    });
});

/* ---------- Documents children regression ---------- */

describe("Documents sidebar active state (SKY-87 regression)", () => {
    function documentsChildren(): {
        overview: { href: string; exact?: boolean };
        allDocuments: { href: string; exact?: boolean };
    } {
        const docs = erpNavGroups
            .flatMap((group) => group.items)
            .find((item) => item.href === "/dashboard/erp/documents");
        const children = docs?.children?.filter(
            (child) =>
                child.href === "/dashboard/erp/documents" ||
                child.href === "/dashboard/erp/documents/list",
        );
        const overview = children?.find(
            (child) => child.href === "/dashboard/erp/documents",
        );
        const allDocuments = children?.find(
            (child) => child.href === "/dashboard/erp/documents/list",
        );
        if (!overview || !allDocuments) {
            throw new Error("Documents sidebar children not found");
        }
        return { overview, allDocuments };
    }

    it("only Overview is active on /dashboard/erp/documents", () => {
        const { overview, allDocuments } = documentsChildren();
        expect(
            isSidebarItemActive("/dashboard/erp/documents", overview),
        ).toBe(true);
        expect(
            isSidebarItemActive("/dashboard/erp/documents", allDocuments),
        ).toBe(false);
    });

    it("only All documents is active on /dashboard/erp/documents/list", () => {
        const { overview, allDocuments } = documentsChildren();
        expect(
            isSidebarItemActive("/dashboard/erp/documents/list", overview),
        ).toBe(false);
        expect(
            isSidebarItemActive("/dashboard/erp/documents/list", allDocuments),
        ).toBe(true);
    });

    it("never activates both children on the same route", () => {
        const { overview, allDocuments } = documentsChildren();
        const routes = [
            "/dashboard/erp/documents",
            "/dashboard/erp/documents/list",
        ];

        for (const route of routes) {
            const active = [
                isSidebarItemActive(route, overview),
                isSidebarItemActive(route, allDocuments),
            ].filter(Boolean);
            expect(active).toHaveLength(1);
        }
    });
});