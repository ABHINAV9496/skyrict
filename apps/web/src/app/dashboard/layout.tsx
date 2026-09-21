import type { Metadata } from "next";

import { ShellRouter } from "@/components/dashboard/shared/shell-router";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
    robots: {
        index: false,
        follow: false,
    },
};

/**
 * The dashboard subtree is fully static so `<Link>` prefetch + the client
 * router cache hold the real page payload instead of only the loading state.
 *
 * Session gating moved to `middleware.ts` (host-surface cookie presence check):
 * the previous `cookies()` read here forced every `/dashboard` route dynamic,
 * which is why prefetches cached only `loading.tsx` and each route switch
 * re-rendered from the server and re-flashed the shimmer.
 */
export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <>
            <ShellRouter>{children}</ShellRouter>
            <Toaster />
        </>
    );
}
