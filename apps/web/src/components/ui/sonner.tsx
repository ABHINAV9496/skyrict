"use client";

import { Toaster as SonnerToaster, toast } from "sonner";

import { useTheme } from "next-themes";

/**
 * Theme-aware Toaster for the app-wide toast surface. Mounted once in the
 * dashboard layout so every workspace page can fire toasts.
 *
 * Toasts auto-dismiss by default; destructive errors opt into a longer
 * duration + optional Retry action via `onApiError` in @/lib/api/error-toast.
 */
export function Toaster() {
    const { resolvedTheme } = useTheme();

    return (
        <SonnerToaster
            theme={resolvedTheme as "light" | "dark" | "system"}
            position="bottom-right"
            richColors
            closeButton
            toastOptions={{
                classNames: {
                    toast: "!rounded-xl shadow-lg",
                    title: "text-sm font-medium",
                    description: "text-xs text-muted-foreground",
                    actionButton:
                        "!h-7 !rounded-lg !px-2.5 !text-[0.8rem] !font-medium",
                    closeButton: "!text-muted-foreground hover:!text-foreground",
                },
            }}
        />
    );
}

export { toast };