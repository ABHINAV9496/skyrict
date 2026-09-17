"use client";

import * as Sentry from "@sentry/nextjs";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { ErrorState } from "@/components/dashboard/erp/error-state";

interface ErrorBoundaryProps {
    children: ReactNode;
    /** Optional custom fallback; defaults to the shared ErrorState card. */
    fallback?: (props: {
        error: Error;
        onRetry: () => void;
    }) => ReactNode;
}

interface ErrorBoundaryState {
    error: Error | null;
}

/**
 * Feature-scoped error boundary. Wraps an individual widget/section on a page
 * so one failing feature renders a retry card instead of taking down the
 * whole route (which is what the nearest `error.tsx` would otherwise do).
 *
 * Retry clears the error and re-renders children from scratch, so mount
 * effects re-run and the failing fetch is genuinely retried. No
 * `window.location.reload()` - sibling form/scroll state on the page must
 * survive a retry.
 */
export class ErrorBoundary extends Component<
    ErrorBoundaryProps,
    ErrorBoundaryState
> {
    state: ErrorBoundaryState = { error: null };

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return { error };
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        Sentry.captureException(error, {
            extra: { componentStack: info.componentStack },
        });
    }

    private handleRetry = () => {
        this.setState({ error: null });
    };

    render() {
        if (this.state.error) {
            if (this.props.fallback) {
                return this.props.fallback({
                    error: this.state.error,
                    onRetry: this.handleRetry,
                });
            }
            return (
                <ErrorState
                    message={
                        this.state.error.message ||
                        "Something went wrong loading this section."
                    }
                    onRetry={this.handleRetry}
                />
            );
        }
        return this.props.children;
    }
}