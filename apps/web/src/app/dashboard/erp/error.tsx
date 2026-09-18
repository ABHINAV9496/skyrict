"use client";

import { RouteError } from "@/components/dashboard/shared/route-error";

export default function ErpError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    return <RouteError error={error} reset={reset} backHref="/dashboard/erp" />;
}