import type { Metadata } from "next";
import { Bricolage_Grotesque, Inter, JetBrains_Mono } from "next/font/google";

import { Providers } from "@/app/providers";
import { site } from "@/config";
import "@/styles/globals.css";
import "flag-icons/css/flag-icons.min.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: {
    default: `${site.name} — AI Business Operating System`,
    template: `%s · ${site.name}`,
  },
  description: site.description,
  keywords: [
    "Skyrict",
    "AI business operating system",
    "business intelligence platform",
    "AI agents for business",
    "ERP analytics",
    "market intelligence",
    "demand planning software",
  ],
  authors: [{ name: site.name }],
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon.svg",
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "/",
    siteName: site.name,
    title: `${site.name} — AI Business Operating System`,
    description: site.description,
  },
  twitter: {
    card: "summary_large_image",
    title: `${site.name} — AI Business Operating System`,
    description: site.description,
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${inter.variable} ${bricolage.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
