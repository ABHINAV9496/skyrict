"use client";

import { RouteError } from "@/components/dashboard/shared/route-error";

export default function AgentsError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return (
        <RouteError
            error={error}
            reset={reset}
            backHref="/agents"
        />
    );
}