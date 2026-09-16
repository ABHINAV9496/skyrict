import { ApiError } from "@/lib/api/http";
import { toast } from "@/components/ui/sonner";

interface OnApiErrorOptions {
    /** Shown beneath the message, e.g. the action that failed. */
    description?: string;
    /**
     * Only for list-load failures, where re-running the load is unambiguous.
     * Mutations get a message-only toast - blindly retrying a POST could
     * double-create a record.
     */
    action?: { label: string; onClick: () => void };
    /** Shown when the failure is not an ApiError (network, timeout, parse). */
    fallback?: string;
}

/**
 * A shared toast-on-error handler for every mutation and list-load catch
 * block. Resolves the message the same way the inline error states do (an
 * `ApiError` carries its normalized backend message; anything else gets the
 * caller's fallback), fires a persistent destructive toast, and dedupes so a
 * burst of identical failures (retries, parallel widget loads) surfaces once.
 *
 * The dedup key includes the HTTP status, not just the rendered text, so two
 * genuinely different failures that share the generic fallback message are
 * NOT collapsed into one event.
 */
let lastError: { key: string; at: number } | null = null;

const DEDUP_WINDOW_MS = 3000;

export function onApiError(error: unknown, options: OnApiErrorOptions = {}) {
    const status = error instanceof ApiError ? error.status : null;
    const message =
        error instanceof ApiError
            ? error.message
            : options.fallback ?? "Request failed. Please try again.";

    const key = `${status ?? "net"}:${message}`;
    const now = Date.now();
    if (lastError && lastError.key === key && now - lastError.at < DEDUP_WINDOW_MS) {
        return;
    }
    lastError = { key, at: now };

    toast.error(message, {
        description: options.description ?? "Try again or check your connection.",
        duration: Infinity,
        action: options.action,
    });
}