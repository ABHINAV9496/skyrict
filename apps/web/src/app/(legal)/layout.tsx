import Link from "next/link";

import { Logo } from "@/components/brand/logo";

export default function LegalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col bg-card px-6 py-10">
      <div className="flex justify-center">
        <Logo className="text-foreground" />
      </div>

      <main className="mx-auto my-auto w-full max-w-2xl py-10">
        {children}
      </main>

      <footer className="mx-auto w-full max-w-2xl text-center">
        <div className="flex items-center justify-center gap-3 border-t border-border/60 pt-4">
          <Link
            href="/terms"
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            Terms of Service
          </Link>
          <span aria-hidden="true" className="text-muted-foreground/40">
            ·
          </span>
          <Link
            href="/privacy"
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            Privacy Policy
          </Link>
        </div>
      </footer>
    </div>
  );
}
