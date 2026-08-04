import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { footerColumns, site } from "@/config";

function Footer() {
  return (
    <footer className="border-t border-border/70 bg-card/60">
      <div className="mx-auto w-full max-w-6xl px-6 py-14">
        <div className="grid gap-10 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div className="max-w-xs space-y-4">
            <Logo className="text-foreground" />
            <p className="text-sm leading-relaxed text-muted-foreground">
              {site.description}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {["Next.js", "React", "TypeScript", "Tailwind"].map((tech) => (
                <span
                  key={tech}
                  className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground"
                >
                  {tech}
                </span>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            {footerColumns.map((column) => (
              <div key={column.title} className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-foreground">
                  {column.title}
                </p>
                <ul className="space-y-2">
                  {column.links.map((link) =>
                    link.soon ? (
                      <li
                        key={link.label}
                        className="text-sm text-muted-foreground/60"
                      >
                        {link.label}
                        <span className="ml-1.5 rounded bg-muted px-1 py-px text-[10px] font-medium text-muted-foreground">
                          soon
                        </span>
                      </li>
                    ) : (
                      <li key={link.label}>
                        <Link
                          href={link.href ?? "#"}
                          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                        >
                          {link.label}
                        </Link>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-12 flex flex-col items-start justify-between gap-3 border-t border-border/70 pt-6 sm:flex-row sm:items-center">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} {site.name}. All rights reserved.
          </p>
          <p className="font-mono text-xs text-muted-foreground/70">
            {`internal truth × external truth \n agents`}
          </p>
        </div>
      </div>
    </footer>
  );
}

export { Footer };
