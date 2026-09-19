import type { Metadata } from "next";
import Link from "next/link";

import { Logo } from "@/components/brand/logo";

export const metadata: Metadata = {
    robots: {
        index: false,
        follow: false,
    },
};

export default function PlanLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <div className="relative grid min-h-dvh bg-card lg:h-dvh lg:grid-rows-1 lg:overflow-hidden">
            <main className="flex min-h-0 flex-col px-6 py-6 lg:overflow-y-auto">
                <div className="flex justify-center">
                    <Logo className="text-foreground" />
                </div>

                <div className="mx-auto my-auto flex w-full max-w-4xl flex-col py-4">
                    {children}
                </div>

                <footer className="mx-auto w-full max-w-sm pb-2 text-center">
                    <div className="flex items-center justify-center gap-3">
                        <Link
                            href="/terms"
                            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
                        >
                            Terms of Service
                        </Link>
                        <span
                            aria-hidden="true"
                            className="text-muted-foreground/40"
                        >
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
            </main>
        </div>
    );
}