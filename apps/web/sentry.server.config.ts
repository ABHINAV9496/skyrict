import * as Sentry from "@sentry/nextjs";

// Server-side Sentry (Next.js route handlers / BFF / server components).
// Guarded the same way as the client config: the DSN is only set in
// staging/production, so dev/test never initialize the SDK.
const dsn = process.env.SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 0.1,
  });
}