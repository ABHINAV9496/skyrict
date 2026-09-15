import * as Sentry from "@sentry/nextjs";

// Client-side Sentry. The DSN is public by design (it rides along in the
// browser bundle), so it uses the NEXT_PUBLIC_ env convention. When it is not
// set - dev/test - init is skipped entirely and no beacon is attempted.
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 0.1,
  });
}