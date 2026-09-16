import { useMemo, useRef } from "react";

/**
 * Latest-wins guard for `useCallback`-based loaders whose deps are mutable
 * (filters, pagination, search). Each `load()` takes a request token; a
 * resolve/error from an earlier invocation is dropped once a newer one has
 * started, so a slow response can never overwrite fresher state with stale
 * data.
 *
 * Use at the top of `load` (`const requestId = requestGuard.next();`) and
 * before every `setStatus`/`setState` write
 * (`if (!requestGuard.isCurrent(requestId)) return;`). The returned object is
 * identity-stable, so list it in the `useCallback` deps for the lint rule
 * without causing re-runs. It complements (not replaces) AbortController
 * where the API wrapper accepts a `fetchOptions` signal.
 */
export function useLatestRequest() {
    const ref = useRef(0);

    return useMemo(
        () => ({
            next: () => ++ref.current,
            isCurrent: (token: number) => token === ref.current,
        }),
        [],
    );
}