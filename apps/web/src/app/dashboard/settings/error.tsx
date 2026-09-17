"use client";

import { RouteError } from "@/components/dashboard/shared/route-error";

export default function SettingsError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return <RouteError error={error} reset={reset} />;
}