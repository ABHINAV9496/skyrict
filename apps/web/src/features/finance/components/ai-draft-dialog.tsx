"use client";

import { useState } from "react";
import { LoaderCircle, Sparkles, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { draftJournalEntry, type DraftEntry } from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

export interface AppliedDraftLine {
  account_code: string;
  debit?: number;
  credit?: number;
}

interface AiDraftDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (lines: AppliedDraftLine[], memo: string) => void;
}

function AiDraftDialog({ open, onOpenChange, onApply }: AiDraftDialogProps) {
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<DraftEntry | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!description.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await draftJournalEntry(description.trim());
      setDraft(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate draft.");
    } finally {
      setLoading(false);
    }
  }

  function handleApply() {
    if (!draft) return;
    const lines: AppliedDraftLine[] = draft.lines.map((line) =>
      line.side === "credit"
        ? { account_code: line.account_code, credit: line.amount }
        : { account_code: line.account_code, debit: line.amount },
    );
    onApply(lines, description.trim());
    onOpenChange(false);
    setDraft(null);
    setDescription("");
  }

  const debitTotal = draft?.lines.filter((l) => l.side === "debit").reduce((s, l) => s + l.amount, 0) ?? 0;
  const creditTotal = draft?.lines.filter((l) => l.side === "credit").reduce((s, l) => s + l.amount, 0) ?? 0;
  const balanced = Math.abs(debitTotal - creditTotal) < 0.005;
  const confidencePct = draft ? Math.round(draft.confidence * 100) : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" />
            AI Draft Entry
          </DialogTitle>
          <DialogDescription>
            Describe the transaction in plain English and let AI draft a balanced journal entry.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="ai-draft-description">Description</Label>
            <div className="flex gap-2">
              <Input
                id="ai-draft-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. Paid 5000 rent for August and 500 utilities to landlord via bank check"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleGenerate();
                }}
              />
              <Button
                onClick={() => void handleGenerate()}
                disabled={loading || !description.trim()}
              >
                {loading ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : (
                  <Sparkles className="size-4" />
                )}
                Generate
              </Button>
            </div>
          </div>

          {error ? (
            <p role="alert" className="flex items-center gap-2 text-xs font-medium text-destructive">
              <TriangleAlert className="size-3.5" />
              {error}
            </p>
          ) : null}

          {draft ? (
            <div className="grid gap-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">
                  Confidence
                </span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-semibold",
                    confidencePct >= 75
                      ? "bg-emerald-100 text-emerald-700"
                      : confidencePct >= 50
                        ? "bg-amber-100 text-amber-700"
                        : "bg-red-100 text-red-700",
                  )}
                >
                  {confidencePct}%
                </span>
              </div>

              {draft.lines.length > 0 ? (
                <div className="grid gap-1.5 rounded-lg border border-border p-3">
                  {draft.lines.map((line, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between gap-2 text-sm"
                    >
                      <div className="min-w-0">
                        <span className="font-mono font-semibold">{line.account_code}</span>{" "}
                        <span className="text-muted-foreground">{line.account_name}</span>
                      </div>
                      <div className="flex items-center gap-2 whitespace-nowrap">
                        {line.description ? (
                          <span className="hidden text-xs text-muted-foreground sm:inline">
                            {line.description}
                          </span>
                        ) : null}
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums",
                            line.side === "debit"
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-blue-100 text-blue-700",
                          )}
                        >
                          {line.side === "debit" ? "Dr" : "Cr"} {line.amount.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}

              {draft.explanation ? (
                <p className="rounded-lg border-l-2 border-primary/30 bg-muted/40 p-3 text-xs text-muted-foreground">
                  {draft.explanation}
                </p>
              ) : null}

              <div
                className={cn(
                  "flex items-center gap-2 text-xs font-medium",
                  balanced ? "text-emerald-600" : "text-amber-600",
                )}
              >
                {balanced ? "Balanced ✓" : `Off by $${Math.abs(debitTotal - creditTotal).toFixed(2)}`}
                <span className="text-muted-foreground">
                  Dr {debitTotal.toFixed(2)} / Cr {creditTotal.toFixed(2)}
                </span>
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleApply} disabled={!draft || draft.lines.length === 0}>
            Apply Draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export { AiDraftDialog };
