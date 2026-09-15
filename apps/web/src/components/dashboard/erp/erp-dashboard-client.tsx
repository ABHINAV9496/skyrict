"use client";

import { useCallback, useEffect, useState } from "react";
import { Blocks, Settings } from "lucide-react";

import { CustomizeMode, type CustomizeLayoutItem } from "./customize-mode";
import { WidgetGrid, type LayoutItem } from "./widget-grid";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import {
    fetchLayout,
    saveLayout,
    resetLayout,
} from "@/lib/dashboard/layout-api";
import { getDefaultLayout } from "@/lib/dashboard/widget-registry";
import { trackWidgetEvent } from "@/lib/dashboard/widget-events";

/**
 * Client component for the ERP dashboard with layout customization.
 *
 * Loads the user's saved layout (or tenant default) and renders widgets
 * in a configurable grid.  The "Customize" button opens a full-screen
 * panel for drag/reorder, show/hide, and size controls.
 */
export function ErpDashboardClient() {
    const [layout, setLayout] = useState<LayoutItem[]>([]);
    const [customizing, setCustomizing] = useState(false);
    const [loaded, setLoaded] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [errorNotice, setErrorNotice] = useState<string | null>(null);

    // Load layout on mount
    useEffect(() => {
        let cancelled = false;
        fetchLayout()
            .then((res) => {
                if (!cancelled) {
                    const effective =
                        res.layout && res.layout.length > 0
                            ? res.layout
                            : getDefaultLayout();
                    setLayout(effective);
                    setLoaded(true);
                }
            })
            .catch(() => {
                // Fallback to default layout if API unavailable
                if (!cancelled) {
                    setLayout(getDefaultLayout());
                    setLoaded(true);
                }
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const handleSave = useCallback(async (newLayout: CustomizeLayoutItem[]) => {
        setIsSaving(true);
        setErrorNotice(null);
        try {
            await saveLayout(newLayout);
            setLayout(newLayout);
            setCustomizing(false);
        } catch (err) {
            setErrorNotice(
                err instanceof Error
                    ? err.message
                    : "Failed to save layout. Please try again.",
            );
        } finally {
            setIsSaving(false);
        }
    }, []);

    const handleReset = useCallback(async () => {
        setIsSaving(true);
        setErrorNotice(null);
        try {
            await resetLayout();
            setLayout(getDefaultLayout());
            setCustomizing(false);
        } catch (err) {
            setErrorNotice(
                err instanceof Error
                    ? err.message
                    : "Failed to reset layout. Please try again.",
            );
        } finally {
            setIsSaving(false);
        }
    }, []);

    const handleWidgetShow = useCallback((widgetId: string) => {
        trackWidgetEvent(widgetId, "open");
    }, []);

    if (!loaded) {
        return (
            <div className="space-y-8">
                <PageHeader
                    title="Business Operations"
                    description="Operations management inventory, sales, cash, and orders, all on one source of truth."
                    icon={Blocks}
                />
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="h-40 rounded-xl border border-border bg-card animate-pulse" />
                    <div className="h-40 rounded-xl border border-border bg-card animate-pulse" />
                    <div className="h-40 rounded-xl border border-border bg-card animate-pulse sm:col-span-2" />
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-8">
            <div className="flex items-start justify-between gap-4">
                <PageHeader
                    title="Business Operations"
                    description="Operations management inventory, sales, cash, and orders, all on one source of truth."
                    icon={Blocks}
                />
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setCustomizing(true)}
                    className="shrink-0"
                >
                    <Settings aria-hidden="true" className="mr-1.5 size-3.5" />
                    Customize
                </Button>
            </div>

            <WidgetGrid layout={layout} onWidgetShow={handleWidgetShow} />

            {customizing && (
                <CustomizeMode
                    layout={layout.map((item, i) => ({
                        ...item,
                        order: item.order ?? i,
                    }))}
                    onSave={handleSave}
                    onReset={handleReset}
                    onClose={() => {
                        setErrorNotice(null);
                        setCustomizing(false);
                    }}
                    errorNotice={errorNotice}
                    isSaving={isSaving}
                />
            )}
        </div>
    );
}
