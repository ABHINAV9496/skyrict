"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BellRing, Check, CheckCheck, Clock, Inbox, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
    getNotificationCounts,
    listNotificationInbox,
    markAllNotificationsRead,
    markNotificationRead,
    snoozeNotification,
    type NotificationItem,
} from "@/lib/api/notifications-api";
import { cn } from "@/lib/utils";

const SEVERITY_DOT: Record<string, string> = {
    low: "bg-sky-500",
    medium: "bg-amber-500",
    high: "bg-orange-500",
    critical: "bg-rose-500",
};

const SEVERITY_LABEL: Record<string, string> = {
    low: "Low",
    medium: "Medium",
    high: "High",
    critical: "Critical",
};

const SEVERITY_BADGE: Record<string, string> = {
    low: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
    medium: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
    high: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
    critical: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
};

function snoozePresets(now: Date): { label: string; until: string }[] {
    const inOneHour = new Date(now.getTime() + 60 * 60 * 1000);
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    const nextWeek = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
    return [
        { label: "In 1 hour", until: inOneHour.toISOString() },
        { label: "Tomorrow 9:00", until: tomorrow.toISOString() },
        { label: "In 1 week", until: nextWeek.toISOString() },
    ];
}

function formatRelative(iso: string, now: Date): string {
    const then = new Date(iso);
    const minutes = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 60000));
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return days === 1 ? "Yesterday" : `${days}d ago`;
}

function formatAbsolute(iso: string): string {
    return new Date(iso).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    });
}

function NotificationRow({
    item,
    now,
    onOpen,
    onRead,
    onSnooze,
}: {
    item: NotificationItem;
    now: Date;
    onOpen: (item: NotificationItem) => void;
    onRead: (id: string) => void;
    onSnooze: (id: string, until: string) => void;
}) {
    const unread = !item.read_at;
    return (
        <li
            role="button"
            tabIndex={0}
            aria-label={`Open notification: ${item.title}`}
            onClick={() => onOpen(item)}
            onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onOpen(item);
                }
            }}
            className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-xl border px-3.5 py-3 transition-colors",
                unread
                    ? "border-primary/25 bg-primary/[0.04] hover:bg-muted/50"
                    : "border-border/60 bg-card/40 opacity-80 hover:bg-muted/40 hover:opacity-100",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
            )}
        >
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2">
                    <span
                        aria-hidden="true"
                        className={cn(
                            "size-2 shrink-0 rounded-full",
                            SEVERITY_DOT[item.severity] ?? SEVERITY_DOT.low,
                        )}
                    />
                    <p className="truncate text-sm font-medium text-foreground">
                        {item.title}
                    </p>
                </div>
                <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                    {item.body}
                </p>
                <p className="text-[0.7rem] text-muted-foreground/80">
                    {item.category.replaceAll("_", " ")} · {SEVERITY_LABEL[item.severity] ?? item.severity} ·{" "}
                    {formatRelative(item.occurred_at, now)}
                    {item.is_pinned && " · Pinned"}
                    {item.is_digest && item.digest_count != null && ` · ${item.digest_count + 1} items`}
                </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
                {unread && (
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Mark as read"
                        title="Mark as read"
                        onClick={(event) => {
                            event.stopPropagation();
                            onRead(item.id);
                        }}
                    >
                        <Check aria-hidden="true" />
                    </Button>
                )}
                {!item.is_pinned && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label="Snooze"
                                title="Snooze"
                                onClick={(event) => event.stopPropagation()}
                            >
                                <Clock aria-hidden="true" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {snoozePresets(now).map((preset) => (
                                <DropdownMenuItem
                                    key={preset.label}
                                    onClick={() => onSnooze(item.id, preset.until)}
                                >
                                    {preset.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </div>
        </li>
    );
}

/**
 * In-panel detail view for one notification - clicking a row swaps the drawer
 * body to this (no separate page), with a back affordance to the list.
 */
function NotificationDetail({
    item,
    now,
    onBack,
    onRead,
    onSnooze,
}: {
    item: NotificationItem;
    now: Date;
    onBack: () => void;
    onRead: (id: string) => void;
    onSnooze: (id: string, until: string) => void;
}) {
    const unread = !item.read_at;
    const payloadEntries = item.payload
        ? Object.entries(item.payload).filter(
              ([, value]) => value !== null && value !== undefined,
          )
        : [];

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="border-b border-border/70 px-2 py-2">
                <Button variant="ghost" size="sm" onClick={onBack}>
                    <ArrowLeft aria-hidden="true" />
                    All notifications
                </Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                <div className="flex flex-wrap items-center gap-2">
                    <span
                        aria-hidden="true"
                        className={cn(
                            "size-2 rounded-full",
                            SEVERITY_DOT[item.severity] ?? SEVERITY_DOT.low,
                        )}
                    />
                    <span
                        className={cn(
                            "rounded-full px-2 py-0.5 text-[0.7rem] font-medium",
                            SEVERITY_BADGE[item.severity] ?? SEVERITY_BADGE.low,
                        )}
                    >
                        {SEVERITY_LABEL[item.severity] ?? item.severity}
                    </span>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[0.7rem] text-muted-foreground">
                        {item.category.replaceAll("_", " ")}
                    </span>
                    {unread ? (
                        <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[0.7rem] font-medium text-primary">
                            Unread
                        </span>
                    ) : (
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[0.7rem] text-muted-foreground">
                            Read
                        </span>
                    )}
                </div>
                <h3 className="mt-3 text-base leading-snug font-semibold text-foreground">
                    {item.title}
                </h3>
                <p className="mt-1.5 text-xs text-muted-foreground">
                    {formatAbsolute(item.occurred_at)}
                </p>

                <p className="mt-4 text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
                    {item.body}
                </p>

                <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
                    <dt className="text-muted-foreground">Module</dt>
                    <dd className="text-foreground">
                        {item.module.replaceAll("_", " ")}
                    </dd>
                    <dt className="text-muted-foreground">Received</dt>
                    <dd className="text-foreground">
                        {formatRelative(item.occurred_at, now)}
                    </dd>
                    {item.is_digest && item.digest_count != null ? (
                        <>
                            <dt className="text-muted-foreground">
                                Grouped items
                            </dt>
                            <dd className="text-foreground">
                                {item.digest_count + 1}
                            </dd>
                        </>
                    ) : null}
                    {item.is_pinned ? (
                        <>
                            <dt className="text-muted-foreground">Pinned</dt>
                            <dd className="text-foreground">Yes</dd>
                        </>
                    ) : null}
                </dl>

                {payloadEntries.length > 0 ? (
                    <div className="mt-4 rounded-xl border border-border/60 bg-muted/30 px-3 py-2.5">
                        <p className="text-[0.7rem] font-medium tracking-wide text-muted-foreground uppercase">
                            Details
                        </p>
                        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                            {payloadEntries.map(([key, value]) => (
                                <Fragment key={key}>
                                    <dt className="text-muted-foreground">
                                        {key.replaceAll("_", " ")}
                                    </dt>
                                    <dd className="break-words text-foreground">
                                        {String(value)}
                                    </dd>
                                </Fragment>
                            ))}
                        </dl>
                    </div>
                ) : null}

                <div className="mt-5 flex items-center gap-2 pb-2">
                    {unread ? (
                        <Button size="sm" onClick={() => onRead(item.id)}>
                            <Check aria-hidden="true" />
                            Mark as read
                        </Button>
                    ) : null}
                    {!item.is_pinned ? (
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button size="sm" variant="outline">
                                    <Clock aria-hidden="true" />
                                    Snooze
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start">
                                {snoozePresets(now).map((preset) => (
                                    <DropdownMenuItem
                                        key={preset.label}
                                        onClick={() =>
                                            onSnooze(item.id, preset.until)
                                        }
                                    >
                                        {preset.label}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    ) : null}
                </div>
            </div>
        </div>
    );
}

/**
 * Notification bell + inbox drawer for the topbar (SKY-93). The drawer is
 * intentionally a Dialog (the codebase has no Sheet primitive) resized into a
 * right-side panel. The inbox is recipient-scoped by the backend; this UI
 * only ever renders the signed-in user's own rows.
 */
export function NotificationCenter() {
    const [open, setOpen] = useState(false);
    const [unreadCount, setUnreadCount] = useState(0);
    const [items, setItems] = useState<NotificationItem[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [selected, setSelected] = useState<NotificationItem | null>(null);

    const refreshCounts = useCallback(() => {
        getNotificationCounts()
            .then((counts) => setUnreadCount(counts.unread_count))
            .catch(() => setUnreadCount(0));
    }, []);

    const loadInbox = useCallback(() => {
        setLoading(true);
        setError(null);
        listNotificationInbox(50)
            .then((page) => {
                setItems(page.items);
                setTotal(page.total);
                setUnreadCount(page.unread_count);
            })
            .catch(() => {
                setError("Could not load notifications. Please try again.");
            })
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        refreshCounts();
    }, [refreshCounts]);

    useEffect(() => {
        if (open) loadInbox();
    }, [open, loadInbox]);

    const handleRead = useCallback(
        (id: string) => {
            setActionError(null);
            markNotificationRead(id)
                .then(() => {
                    setItems((current) =>
                        current.map((item) =>
                            item.id === id ? { ...item, read_at: new Date().toISOString() } : item,
                        ),
                    );
                    refreshCounts();
                })
                .catch(() => {
                    setActionError("Could not mark that notification as read.");
                });
        },
        [refreshCounts],
    );

    const handleReadAll = useCallback(() => {
        setActionError(null);
        markAllNotificationsRead()
            .then((result) => {
                if (result.marked === 0) return;
                setItems((current) =>
                    current.map((item) => ({
                        ...item,
                        read_at: item.read_at ?? new Date().toISOString(),
                    })),
                );
                refreshCounts();
            })
            .catch(() => {
                setActionError("Could not clear your notifications.");
            });
    }, [refreshCounts]);

    const handleSnooze = useCallback(
        (id: string, until: string) => {
            setActionError(null);
            snoozeNotification(id, until)
                .then((result) => {
                    if (!result.snoozed) return;
                    setItems((current) => current.filter((item) => item.id !== id));
                    refreshCounts();
                })
                .catch((reason: unknown) => {
                    const message =
                        reason instanceof Error
                            ? reason.message
                            : "Could not snooze that notification.";
                    setActionError(
                        message === "This notification cannot be snoozed"
                            ? "This notification can't be snoozed."
                            : "Could not snooze that notification.",
                    );
                });
        },
        [refreshCounts],
    );

    return (
        <>
            <button
                type="button"
                aria-label={unreadCount > 0 ? `Notifications (${unreadCount} unread)` : "Notifications"}
                title="Notifications"
                onClick={() => setOpen(true)}
                className="relative flex size-9 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60"
            >
                <BellRing aria-hidden="true" className="size-5" />
                {unreadCount > 0 && (
                    <span className="absolute top-1 right-1 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[0.65rem] leading-4 font-semibold text-white">
                        {unreadCount > 99 ? "99+" : unreadCount}
                    </span>
                )}
            </button>

            <Dialog
                open={open}
                onOpenChange={(next) => {
                    setOpen(next);
                    // Reopening always lands on the list, never a stale detail.
                    if (!next) setSelected(null);
                }}
            >
                <DialogContent
                    showCloseButton={false}
                    className="top-0 right-0 bottom-0 left-auto h-dvh w-full max-w-md translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-0 rounded-none rounded-l-xl p-0 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-0 data-open:slide-in-from-right-5 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-0 data-closed:slide-out-to-right-5"
                >
                    <DialogHeader className="border-b border-border/70 px-4 py-3">
                        {selected ? (
                            <div className="flex items-center gap-1.5">
                                <Button
                                    variant="ghost"
                                    size="icon-sm"
                                    aria-label="Back to all notifications"
                                    onClick={() => setSelected(null)}
                                >
                                    <ArrowLeft aria-hidden="true" />
                                </Button>
                                <DialogTitle className="text-base">
                                    Notification details
                                </DialogTitle>
                            </div>
                        ) : (
                            <div className="flex items-center justify-between gap-2">
                                <DialogTitle className="flex items-center gap-2 text-base">
                                    <Inbox aria-hidden="true" className="size-4 text-primary" />
                                    Notifications
                                </DialogTitle>
                                <div className="flex items-center gap-1.5">
                                    {unreadCount > 0 && (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => void handleReadAll()}
                                        >
                                            <CheckCheck aria-hidden="true" />
                                            Mark all read
                                        </Button>
                                    )}
                                    <Button variant="ghost" size="icon-sm" asChild>
                                        <Link
                                            href="/settings/notifications"
                                            prefetch={false}
                                            aria-label="Notification preferences"
                                            title="Notification preferences"
                                        >
                                            <Settings2 aria-hidden="true" />
                                        </Link>
                                    </Button>
                                </div>
                            </div>
                        )}
                        <DialogDescription className="sr-only">
                            Your notification inbox with read, snooze, and preferences.
                        </DialogDescription>
                    </DialogHeader>

                    {selected ? (
                        <NotificationDetail
                            item={selected}
                            now={new Date()}
                            onBack={() => setSelected(null)}
                            onRead={(id) => {
                                handleRead(id);
                                // Keep the open detail in sync with the list.
                                setSelected((current) =>
                                    current && current.id === id
                                        ? {
                                              ...current,
                                              read_at: new Date().toISOString(),
                                          }
                                        : current,
                                );
                            }}
                            onSnooze={(id, until) => {
                                handleSnooze(id, until);
                                // Snoozed rows leave the inbox - back to the list.
                                setSelected(null);
                            }}
                        />
                    ) : (
                    <div className="min-h-0 flex-1 overflow-y-auto">
                        {actionError && (
                            <div className="border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive">
                                {actionError}
                            </div>
                        )}
                        {loading ? (
                            <div className="space-y-3 px-4 py-4">
                                {Array.from({ length: 5 }).map((_, index) => (
                                    <Skeleton key={index} className="h-14 w-full rounded-lg" />
                                ))}
                            </div>
                        ) : error ? (
                            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                                {error}
                            </div>
                        ) : items.length === 0 ? (
                            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
                                <Inbox aria-hidden="true" className="size-8 text-muted-foreground/50" />
                                <p className="text-sm font-medium text-foreground">You&apos;re all caught up</p>
                                <p className="text-xs text-muted-foreground">
                                    {total === 0
                                        ? "No notifications yet."
                                        : "No unread notifications."}
                                </p>
                            </div>
                        ) : (
                            <ul className="flex flex-col gap-2 px-3 py-3">
                                {items.map((item) => (
                                    <NotificationRow
                                        key={item.id}
                                        item={item}
                                        now={new Date()}
                                        onOpen={setSelected}
                                        onRead={handleRead}
                                        onSnooze={handleSnooze}
                                    />
                                ))}
                            </ul>
                        )}
                    </div>
                    )}

                    <div className="border-t border-border/70 px-4 py-2.5">
                        <Button variant="ghost" size="sm" className="w-full" asChild>
                            <Link href="/settings/notifications" prefetch={false}>
                                <Settings2 aria-hidden="true" />
                                Notification preferences
                            </Link>
                        </Button>
                    </div>
                </DialogContent>
            </Dialog>
        </>
    );
}
