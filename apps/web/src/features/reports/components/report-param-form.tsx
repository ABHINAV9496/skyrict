"use client";

import { Spinner } from "@/components/ui/spinner";
import { Download, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ReportParamField } from "@/lib/reports/params";

interface ReportParamFormProps {
  fields: ReportParamField[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  onRun: () => void;
  onExport: () => void;
  running: boolean;
  exporting: boolean;
}

export function ReportParamForm({
  fields,
  values,
  onChange,
  onRun,
  onExport,
  running,
  exporting,
}: ReportParamFormProps) {
  const busy = running || exporting;

  return (
    <form
      className="rounded-xl border border-border bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onRun();
      }}
    >
      <h2 className="font-display text-sm font-semibold text-foreground">Parameters</h2>

      {fields.length > 0 ? (
        <div className="mt-3 space-y-3">
          {fields.map((field) => (
            <div key={field.name} className="space-y-1.5">
              <Label htmlFor={`param-${field.name}`}>{field.label}</Label>
              <Input
                id={`param-${field.name}`}
                name={field.name}
                type={field.kind === "date" ? "date" : "text"}
                required={field.required}
                value={values[field.name] ?? ""}
                onChange={(event) => onChange(field.name, event.target.value)}
              />
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          This report runs without parameters.
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {running ? (
            <Spinner aria-hidden="true" className="size-4" />
          ) : (
            <Play aria-hidden="true" className="size-4" />
          )}
          {running ? "Running…" : "Run report"}
        </Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onExport}>
          <Download aria-hidden="true" className="size-4" />
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
      </div>
    </form>
  );
}