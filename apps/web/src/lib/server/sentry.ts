import * as Sentry from "@sentry/nextjs";

// Server-side error capture used by the BFF for failures that would otherwise
// be swallowed by the caller. The DSN guard keeps this a strict no-op in
// dev/test and mirrors the guarded init in sentry.server.config.ts.

export function captureBffException(
    error: unknown,
    path: string,
    target: string,
): void {
    if (!process.env.SENTRY_DSN) return;
    Sentry.withScope((scope) => {
        scope.setTag("bff.path", path);
        scope.setTag("bff.target", target);
        Sentry.captureException(error);
    });
}