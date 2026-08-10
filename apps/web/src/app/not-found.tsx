import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Page not found",
  robots: {
    index: false,
    follow: false,
  },
};

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-card px-6 py-16 text-center">
      <Logo className="text-foreground" />
      <p className="mt-10 font-mono text-xs uppercase tracking-[0.2em] text-primary">
        404
      </p>
      <h1 className="mt-4 font-display text-3xl font-semibold tracking-tight text-foreground">
        This page could not be found.
      </h1>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
        The page you were looking for doesn&apos;t exist or has moved. Head
        back to the Skyrict homepage to keep going.
      </p>
      <Button asChild className="mt-8">
        <Link href="/">Back to home</Link>
      </Button>
    </main>
  );
}
