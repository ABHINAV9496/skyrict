"use client";

import { ThemeProvider } from "next-themes";

import { SessionProvider } from "@/lib/auth/session";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
      <SessionProvider>{children}</SessionProvider>
    </ThemeProvider>
  );
}
