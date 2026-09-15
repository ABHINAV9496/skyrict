"use client";

import * as Sentry from "@sentry/nextjs";
import NextError from "next/error";
import { useEffect } from "react";

// Root error boundary (App Router). Fires for errors that the layout-level
// error.tsx cannot handle and reports them to Sentry. The SDK is a no-op when
// no DSN is configured (dev/test), so this is safe everywhere.
export default function GlobalError({
    error,
}: {
    error: Error & { digest?: string };
}) {
    useEffect(() => {
        Sentry.captureException(error);
    }, [error]);

    return (
        <html lang="en">
            <body>
                <NextError statusCode={500} title="Something went wrong" />
            </body>
        </html>
    );
}