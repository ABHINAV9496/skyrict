"use client";

import { Spinner } from "@/components/ui/spinner";
import { useCallback, useEffect, useState } from "react";
import { SlidersHorizontal, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useModuleAccess } from "@/lib/access/modules";
import {
    getAutomationSettings,
    recommendInvoiceNumberingScheme,
    updateAutomationSettings,
    type InvoiceNumberingScheme,
} from "@/lib/api/finance-api";
import { apiErrorMessage as message } from "@/lib/api/error-toast";

type PageStatus =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready" };

type Notice = { tone: "success" | "error"; text: string };

export function FinanceSettings() {
    const { permissions } = useModuleAccess();
    const canWrite =
        permissions.includes("*") || permissions.includes("erp.finance.write");

    const [status, setStatus] = useState<PageStatus>({ state: "loading" });
    const [threshold, setThreshold] = useState("");
    const [numberingScheme, setNumberingScheme] = useState("");
    const [recommendation, setRecommendation] =
        useState<InvoiceNumberingScheme | null>(null);
    const [notice, setNotice] = useState<Notice | null>(null);
    const [saving, setSaving] = useState(false);
    const [recommending, setRecommending] = useState(false);

    useEffect(() => {
        let alive = true;
        getAutomationSettings()
            .then((settings) => {
                if (!alive) return;
                setThreshold(String(settings.working_capital_threshold));
                setNumberingScheme(settings.invoice_numbering_scheme ?? "");
                setStatus({ state: "ready" });
            })
            .catch((error) => {
                if (alive) {
                    setStatus({
                        state: "error",
                        message: message(
                            error,
                            "Could not load finance settings.",
                        ),
                    });
                }
            });
        return () => {
            alive = false;
        };
    }, []);

    const recommend = useCallback(async () => {
        setRecommending(true);
        setNotice(null);
        try {
            setRecommendation(await recommendInvoiceNumberingScheme());
        } catch (error) {
            setNotice({
                tone: "error",
                text: message(
                    error,
                    "Could not generate a numbering-scheme recommendation.",
                ),
            });
        } finally {
            setRecommending(false);
        }
    }, []);

    const save = useCallback(async () => {
        setSaving(true);
        setNotice(null);
        try {
            const settings = await updateAutomationSettings(
                Number(threshold),
                numberingScheme || undefined,
            );
            setNumberingScheme(settings.invoice_numbering_scheme ?? "");
            setNotice({
                tone: "success",
                text: "Finance settings saved.",
            });
        } catch (error) {
            setNotice({
                tone: "error",
                text: message(error, "Could not save finance settings."),
            });
        } finally {
            setSaving(false);
        }
    }, [threshold, numberingScheme]);

    if (status.state === "loading") {
        return (
            <div className="flex items-center justify-center py-16">
                <Spinner
                    aria-hidden="true"
                    className="size-6 text-muted-foreground"
                />
            </div>
        );
    }

    if (status.state === "error") {
        return (
            <div className="rounded-lg border border-border bg-card p-6 text-sm text-destructive">
                {status.message}
            </div>
        );
    }

    return (
        <div>
            <PageHeader
                title="Finance settings"
                description="Automation defaults for this workspace."
            />
            <div className="mt-6 space-y-6">
                <section className="rounded-xl border border-border bg-card p-4">
                    <h2 className="font-display text-sm font-semibold text-foreground">
                        Working capital
                    </h2>
                    <div className="mt-3 flex flex-wrap items-end gap-2">
                        <div className="w-48 space-y-1.5">
                            <Label htmlFor="working-capital-threshold">
                                Alert threshold
                            </Label>
                            <Input
                                id="working-capital-threshold"
                                type="number"
                                min="0"
                                step="0.1"
                                value={threshold}
                                onChange={(event) =>
                                    setThreshold(event.target.value)
                                }
                                disabled={!canWrite}
                            />
                        </div>
                    </div>
                </section>

                <section className="rounded-xl border border-border bg-card p-4">
                    <div className="flex items-center gap-2">
                        <SlidersHorizontal
                            aria-hidden="true"
                            className="size-4 text-primary"
                        />
                        <h2 className="font-display text-sm font-semibold text-foreground">
                            Invoice numbering scheme
                        </h2>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                        Today invoices are numbered{" "}
                        <span className="font-mono">INV-YYYY-#####</span>.
                        Choose a scheme to apply to future invoices; changing it
                        never renumbers existing invoices.
                    </p>
                    <div className="mt-3 flex flex-wrap items-end gap-2">
                        <div className="w-72 space-y-1.5">
                            <Label htmlFor="numbering-scheme">Scheme</Label>
                            <Input
                                id="numbering-scheme"
                                placeholder="INV-YYYY-#####"
                                value={numberingScheme}
                                onChange={(event) =>
                                    setNumberingScheme(event.target.value)
                                }
                                disabled={!canWrite}
                            />
                        </div>
                        <Button
                            type="button"
                            variant="outline"
                            disabled={recommending}
                            onClick={() => void recommend()}
                        >
                            {recommending ? (
                                <Spinner
                                    aria-hidden="true"
                                    className="size-4"
                                />
                            ) : (
                                <Sparkles
                                    aria-hidden="true"
                                    className="size-4"
                                />
                            )}
                            Recommend
                        </Button>
                    </div>

                    {recommendation ? (
                        <div className="mt-3 rounded-lg bg-muted/50 p-3 text-sm">
                            <p>
                                <span className="font-mono text-base font-semibold text-foreground">
                                    {recommendation.scheme}
                                </span>
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                                {recommendation.rationale}
                            </p>
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="mt-2"
                                disabled={!canWrite}
                                onClick={() =>
                                    setNumberingScheme(recommendation.scheme)
                                }
                            >
                                Use this scheme
                            </Button>
                        </div>
                    ) : null}
                </section>

                {canWrite ? (
                    <div className="flex items-center gap-3">
                        <Button
                            type="button"
                            disabled={saving || !threshold}
                            onClick={() => void save()}
                        >
                            {saving ? (
                                <Spinner
                                    aria-hidden="true"
                                    className="size-4"
                                />
                            ) : null}
                            Save settings
                        </Button>
                        {notice ? (
                            <span
                                role="status"
                                className={
                                    notice.tone === "success"
                                        ? "text-xs text-emerald-700 dark:text-emerald-400"
                                        : "text-xs font-medium text-destructive"
                                }
                            >
                                {notice.text}
                            </span>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </div>
    );
}
