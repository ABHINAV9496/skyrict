/**
 * Widget interaction telemetry - client-side batching + flush.
 *
 * Records open/hide events per widget and flushes them to the API
 * every 10 seconds (or on page unload).  Fire-and-forget: telemetry
 * failure is never fatal.
 */

import { recordEvents, type EventPayload } from "./layout-api";

/** Maximum events to buffer before force-flushing. */
const MAX_BUFFER_SIZE = 50;

/** Flush interval in milliseconds. */
const FLUSH_INTERVAL_MS = 10_000;

let buffer: EventPayload[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;
let initialized = false;

/**
 * Record a widget interaction event.
 *
 * Events are buffered and flushed periodically.  Call this from
 * WidgetGrid's onWidgetShow callback and from hide/toggle actions.
 */
export function trackWidgetEvent(widgetId: string, event: "open" | "hide"): void {
  if (!initialized) {
    init();
  }

  buffer.push({ widget_id: widgetId, event });

  if (buffer.length >= MAX_BUFFER_SIZE) {
    void flush();
  }
}

/**
 * Initialize the telemetry system (called once on first event).
 */
function init(): void {
  if (initialized) return;
  initialized = true;

  // Flush on page unload (best-effort)
  if (typeof window !== "undefined") {
    window.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("beforeunload", handleBeforeUnload);
  }

  // Periodic flush
  flushTimer = setInterval(() => {
    void flush();
  }, FLUSH_INTERVAL_MS);
}

/**
 * Flush buffered events to the API.
 */
async function flush(): Promise<void> {
  if (buffer.length === 0) return;

  const events = [...buffer];
  buffer = [];

  try {
    await recordEvents(events);
  } catch {
    // Fire-and-forget: telemetry failure is non-fatal.
    // Silently drop events on failure.
  }
}

function handleVisibilityChange(): void {
  if (document.visibilityState === "hidden") {
    void flush();
  }
}

function handleBeforeUnload(): void {
  // Synchronous best-effort: use sendBeacon if available
  if (buffer.length > 0 && typeof navigator !== "undefined" && navigator.sendBeacon) {
    const payload = JSON.stringify({ events: buffer });
    navigator.sendBeacon("/api/v1/dashboards/me/events", payload);
    buffer = [];
  }
}

/**
 * Flush pending events and clean up timers.
 * Call this on component unmount or app shutdown.
 */
export function teardownTelemetry(): void {
  if (flushTimer !== null) {
    clearInterval(flushTimer);
    flushTimer = null;
  }
  void flush();
}
