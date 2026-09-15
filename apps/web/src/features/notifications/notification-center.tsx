"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { BellRing, Check, CheckCheck, Clock, Inbox, Settings2 } from "lucide-react";

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

function NotificationRow({
    item,
    now,
    onRead,
    onSnooze,
}: {
    item: NotificationItem;
    now: Date;
    onRead: (id: string) => void;
    onSnooze: (id: string, until: string) => void;
}) {
    const unread = !item.read_at;
    return (
        <li
            className={cn(
                "flex gap-2.5 border-b border-border/60 px-4 py-3 transition-colors",
                unread && "bg-muted/25 hover:bg-muted/40",
                !unread && "opacity-75 hover:bg-muted/20",
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
                        onClick={() => onRead(item.id)}
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

            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent
                    showCloseButton={false}
                    className="top-0 right-0 bottom-0 left-auto h-dvh w-full max-w-md translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-0 rounded-none rounded-l-xl p-0 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-0 data-open:slide-in-from-right-5 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-0 data-closed:slide-out-to-right-5"
                >
                    <DialogHeader className="border-b border-border/70 px-4 py-3">
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
                                        href="/dashboard/settings/notifications"
                                        aria-label="Notification preferences"
                                        title="Notification preferences"
                                    >
                                        <Settings2 aria-hidden="true" />
                                    </Link>
                                </Button>
                            </div>
                        </div>
                        <DialogDescription className="sr-only">
                            Your notification inbox with read, snooze, and preferences.
                        </DialogDescription>
                    </DialogHeader>

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
                            <ul className="divide-y-0">
                                {items.map((item) => (
                                    <NotificationRow
                                        key={item.id}
                                        item={item}
                                        now={new Date()}
                                        onRead={handleRead}
                                        onSnooze={handleSnooze}
                                    />
                                ))}
                            </ul>
                        )}
                    </div>

                    <div className="border-t border-border/70 px-4 py-2.5">
                        <Button variant="ghost" size="sm" className="w-full" asChild>
                            <Link href="/dashboard/settings/notifications">
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