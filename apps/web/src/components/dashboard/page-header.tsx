import type { LucideIcon } from "lucide-react";

interface PageHeaderProps {
  title: string;
  description: string;
  icon?: LucideIcon;
}

export function PageHeader({ title, description, icon: Icon }: PageHeaderProps) {
  return (
    <div className="flex items-start gap-3">
      {Icon ? (
        <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-primary">
          <Icon aria-hidden="true" className="size-5" />
        </div>
      ) : null}
      <div className="space-y-1">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}
